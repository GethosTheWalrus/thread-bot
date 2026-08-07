import 'package:flutter/material.dart';
import 'package:threadbot/models/autonomy.dart';
import 'package:threadbot/services/autonomy_api.dart';
import 'package:threadbot/widgets/agent_workspace_ui.dart';

/// Adaptive heartbeat configuration sheet for an agent.
///
/// Shows current status and lets the operator enable/disable, configure
/// min/max wake intervals, set idle backoff, and trigger an immediate wake.
class HeartbeatConfigSheet extends StatefulWidget {
  final String agentId;
  final String agentName;
  final AutonomyApiService api;
  const HeartbeatConfigSheet({
    super.key,
    required this.agentId,
    required this.agentName,
    required this.api,
  });

  @override
  State<HeartbeatConfigSheet> createState() => _HeartbeatConfigSheetState();

  static Future<void> show(
    BuildContext context, {
    required String agentId,
    required String agentName,
    required AutonomyApiService api,
  }) {
    return showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => HeartbeatConfigSheet(
        agentId: agentId,
        agentName: agentName,
        api: api,
      ),
    );
  }
}

class _HeartbeatConfigSheetState extends State<HeartbeatConfigSheet> {
  HeartbeatStatus? _status;
  bool _loading = true;
  bool _busy = false;
  String? _error;

  final _minController = TextEditingController(text: '300');
  final _maxController = TextEditingController(text: '3600');
  final _backoffController = TextEditingController(text: '2.0');
  bool _enabled = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _minController.dispose();
    _maxController.dispose();
    _backoffController.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final status = await widget.api.heartbeat(widget.agentId);
      if (!mounted) return;
      setState(() {
        _status = status;
        _enabled = status.enabled;
        _minController.text = status.minWakeSeconds.toString();
        _maxController.text = status.maxWakeSeconds.toString();
        _backoffController.text = status.idleBackoffFactor.toString();
        _loading = false;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = 'Failed to load heartbeat: $e';
        _loading = false;
      });
    }
  }

  Future<void> _save() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final minWake = int.tryParse(_minController.text) ?? 300;
      final maxWake = int.tryParse(_maxController.text) ?? 3600;
      final backoff = double.tryParse(_backoffController.text) ?? 2.0;
      final config = HeartbeatConfig(
        enabled: _enabled,
        minWakeSeconds: minWake.clamp(30, 86400),
        maxWakeSeconds: maxWake.clamp(30, 604800),
        idleBackoffFactor: backoff.clamp(1.0, 10.0),
        expectedRevision: _status?.revision,
      );
      final updated = await widget.api.updateHeartbeat(widget.agentId, config);
      if (!mounted) return;
      setState(() {
        _status = updated;
        _busy = false;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(_enabled ? 'Heartbeat enabled' : 'Heartbeat disabled'),
        ),
      );
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = 'Could not update heartbeat: $e';
        _busy = false;
      });
    }
  }

  Future<void> _wakeNow() async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final status = await widget.api.wakeHeartbeat(widget.agentId);
      if (!mounted) return;
      setState(() {
        _status = status;
        _busy = false;
      });
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('Wake signal sent')));
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = 'Could not wake: $e';
        _busy = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final viewInsets = MediaQuery.of(context).viewInsets;
    return SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 680),
          child: Material(
            color: agentSurface,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(22)),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(
                20,
                12,
                20,
                24,
              ).add(viewInsets),
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Center(
                      child: Container(
                        width: 38,
                        height: 4,
                        decoration: BoxDecoration(
                          color: Colors.white24,
                          borderRadius: BorderRadius.circular(4),
                        ),
                      ),
                    ),
                    const SizedBox(height: 18),
                    Row(
                      children: [
                        Expanded(
                          child: AgentIdentity(
                            name: widget.agentName,
                            radius: 18,
                          ),
                        ),
                        IconButton(
                          tooltip: 'Close heartbeat settings',
                          onPressed: _busy
                              ? null
                              : () => Navigator.pop(context),
                          icon: const Icon(Icons.close_rounded),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    const Text(
                      'Adaptive heartbeat',
                      style: TextStyle(
                        color: Color(0xFFA78BFA),
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const Text(
                      'Let this agent check its mandate on a bounded, self-adjusting cadence.',
                      style: TextStyle(color: Colors.white54, height: 1.4),
                    ),
                    const SizedBox(height: 18),
                    if (_loading)
                      const Padding(
                        padding: EdgeInsets.all(32),
                        child: Center(child: CircularProgressIndicator()),
                      )
                    else ...[
                      if (_status != null) _statusCard(_status!),
                      const SizedBox(height: 14),
                      AgentSection(
                        title: 'Schedule',
                        description:
                            'Idle checks back off automatically up to the maximum interval.',
                        child: Column(
                          children: [
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: const Text('Enable heartbeat'),
                              subtitle: const Text(
                                'Run this agent automatically without a new message.',
                              ),
                              value: _enabled,
                              onChanged: _busy
                                  ? null
                                  : (value) => setState(() => _enabled = value),
                            ),
                            const SizedBox(height: 8),
                            LayoutBuilder(
                              builder: (_, constraints) {
                                final narrow = constraints.maxWidth < 500;
                                final fields = [
                                  _numberField(
                                    _minController,
                                    'Minimum interval (seconds)',
                                  ),
                                  _numberField(
                                    _maxController,
                                    'Maximum interval (seconds)',
                                  ),
                                ];
                                return narrow
                                    ? Column(
                                        children: [
                                          fields[0],
                                          const SizedBox(height: 10),
                                          fields[1],
                                        ],
                                      )
                                    : Row(
                                        children: [
                                          Expanded(child: fields[0]),
                                          const SizedBox(width: 10),
                                          Expanded(child: fields[1]),
                                        ],
                                      );
                              },
                            ),
                            const SizedBox(height: 10),
                            TextField(
                              controller: _backoffController,
                              decoration: const InputDecoration(
                                labelText: 'Idle backoff factor (1.0 – 10.0)',
                              ),
                              keyboardType:
                                  const TextInputType.numberWithOptions(
                                    decimal: true,
                                  ),
                              enabled: !_busy,
                            ),
                          ],
                        ),
                      ),
                      if (_error != null) ...[
                        const SizedBox(height: 2),
                        Text(
                          _error!,
                          style: const TextStyle(color: Colors.redAccent),
                        ),
                      ],
                      const SizedBox(height: 10),
                      Wrap(
                        spacing: 10,
                        runSpacing: 10,
                        alignment: WrapAlignment.end,
                        children: [
                          if (_enabled)
                            OutlinedButton.icon(
                              onPressed: _busy ? null : _wakeNow,
                              icon: const Icon(Icons.bolt_rounded),
                              label: const Text('Wake now'),
                            ),
                          FilledButton.icon(
                            onPressed: _busy ? null : _save,
                            icon: _busy
                                ? const SizedBox(
                                    width: 16,
                                    height: 16,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : const Icon(Icons.save_outlined),
                            label: const Text('Save heartbeat'),
                          ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _numberField(TextEditingController controller, String label) =>
      TextField(
        controller: controller,
        decoration: InputDecoration(labelText: label),
        keyboardType: TextInputType.number,
        enabled: !_busy,
      );

  Widget _statusCard(HeartbeatStatus status) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: agentSurfaceRaised,
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: agentBorder),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            AgentStatusPill(status.operationalStatus),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                status.statusLabel,
                style: const TextStyle(color: Colors.white60),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 24,
          runSpacing: 8,
          children: [
            if (status.nextWakeAt != null)
              _statusFact('Next wake', _formatTime(status.nextWakeAt!)),
            if (status.lastWakeAt != null)
              _statusFact('Last wake', _formatTime(status.lastWakeAt!)),
            if (status.lastDecision != null)
              _statusFact('Last decision', status.lastDecision!),
            if (status.consecutiveNoops > 0)
              _statusFact('Idle checks', '${status.consecutiveNoops}'),
          ],
        ),
        if (status.lastError != null) ...[
          const SizedBox(height: 10),
          Text(
            status.lastError!,
            style: const TextStyle(color: Colors.redAccent),
          ),
        ],
      ],
    ),
  );

  Widget _statusFact(String label, String value) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(label, style: const TextStyle(color: Colors.white38, fontSize: 11)),
      Text(value, style: const TextStyle(fontWeight: FontWeight.w600)),
    ],
  );

  String _formatTime(DateTime t) {
    final local = t.toLocal();
    return '${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}';
  }
}
