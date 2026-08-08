import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:threadbot/models/phase2.dart';
import 'package:threadbot/services/phase2_api.dart';

class ThreadApprovalsPanel extends StatefulWidget {
  final String? threadId;
  final Phase2ApiService api;
  final VoidCallback? onChanged;

  const ThreadApprovalsPanel({
    super.key,
    required this.threadId,
    required this.api,
    this.onChanged,
  });

  @override
  State<ThreadApprovalsPanel> createState() => _ThreadApprovalsPanelState();
}

class _ThreadApprovalsPanelState extends State<ThreadApprovalsPanel> {
  List<Approval> _approvals = const [];
  final Set<String> _busy = {};
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (widget.threadId == null) {
      setState(() {
        _approvals = const [];
        _loading = false;
      });
      return;
    }
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final approvals = await widget.api.approvals(threadId: widget.threadId);
      if (!mounted) return;
      setState(() {
        _approvals = approvals
            .where((approval) => approval.status.toLowerCase() == 'pending')
            .toList();
        _loading = false;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Could not load approvals: $error';
      });
    }
  }

  Future<void> _decide(Approval approval, String decision) async {
    if (_busy.contains(approval.id)) return;
    setState(() {
      _busy.add(approval.id);
      _error = null;
    });
    try {
      await widget.api.decide(approval.id, decision);
      await _load();
      widget.onChanged?.call();
    } catch (error) {
      if (mounted)
        setState(() => _error = 'Decision could not be saved: $error');
    } finally {
      if (mounted) setState(() => _busy.remove(approval.id));
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.threadId == null) {
      return _message('Approvals are available after this thread is saved.');
    }
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  'Pending approvals',
                  style: TextStyle(fontSize: 15, fontWeight: FontWeight.w700),
                ),
              ),
              IconButton(
                onPressed: _load,
                icon: const Icon(Icons.refresh_rounded),
                tooltip: 'Refresh approvals',
              ),
            ],
          ),
          if (_error != null) ...[
            Text(
              _error!,
              style: const TextStyle(color: Colors.redAccent, fontSize: 12),
            ),
            const SizedBox(height: 8),
          ],
          if (_approvals.isEmpty)
            _message('No pending approvals for this thread.')
          else
            ..._approvals.map(_card),
        ],
      ),
    );
  }

  Widget _message(String text) => Padding(
    padding: const EdgeInsets.all(24),
    child: Text(
      text,
      textAlign: TextAlign.center,
      style: const TextStyle(color: Colors.white54),
    ),
  );

  Widget _card(Approval approval) {
    final busy = _busy.contains(approval.id);
    final agent =
        approval.agentName ??
        approval.agentHandle ??
        approval.agentId ??
        'Unknown agent';
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: const Color(0xFF1C1C26),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.white12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              const Icon(
                Icons.shield_outlined,
                color: Color(0xFFF59E0B),
                size: 19,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  approval.toolIdentity ?? approval.actionId,
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
              ),
              _badge(
                approval.riskLevel.isEmpty
                    ? 'risk unknown'
                    : approval.riskLevel,
              ),
            ],
          ),
          const SizedBox(height: 10),
          _detail('Agent', agent),
          _detail('Target', _format(approval.target)),
          _detail('Arguments', _format(approval.arguments)),
          _detail('Why', _format(approval.explanation)),
          if (approval.expiresAt != null)
            _detail('Expires', approval.expiresAt!.toLocal().toString()),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: busy ? null : () => _decide(approval, 'denied'),
                  child: const Text('Deny'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: FilledButton(
                  onPressed: busy ? null : () => _decide(approval, 'approved'),
                  child: busy
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Text('Approve'),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _detail(String label, String value) => Padding(
    padding: const EdgeInsets.only(bottom: 5),
    child: RichText(
      text: TextSpan(
        style: const TextStyle(fontSize: 12, color: Colors.white70),
        children: [
          TextSpan(
            text: '$label: ',
            style: const TextStyle(
              color: Colors.white54,
              fontWeight: FontWeight.w600,
            ),
          ),
          TextSpan(text: value),
        ],
      ),
    ),
  );

  Widget _badge(String value) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 4),
    decoration: BoxDecoration(
      color: Colors.white10,
      borderRadius: BorderRadius.circular(6),
    ),
    child: Text(
      value,
      style: const TextStyle(fontSize: 10, color: Colors.white70),
    ),
  );

  String _format(Map<String, dynamic> value) =>
      value.isEmpty ? '—' : const JsonEncoder.withIndent('  ').convert(value);
}
