import 'package:flutter/material.dart';
import 'package:threadbot/models/autonomy.dart';
import 'package:threadbot/services/autonomy_api.dart';

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

  static Future<void> show(BuildContext context, {
    required String agentId,
    required String agentName,
    required AutonomyApiService api,
  }) {
    return showModalBottomSheet(
      context: context,
      isScrollControlled: true,
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
        SnackBar(content: Text(_enabled ? 'Heartbeat enabled' : 'Heartbeat disabled')),
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
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Wake signal sent')),
      );
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
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 24).add(viewInsets),
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
                  const Icon(Icons.favorite, size: 20),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Adaptive heartbeat · ${widget.agentName}',
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              if (_loading)
                const Padding(
                  padding: EdgeInsets.all(20),
                  child: Center(child: CircularProgressIndicator()),
                )
              else ...[
                if (_status != null)
                  Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: .05),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Status: ${_status!.statusLabel}',
                          style: const TextStyle(fontWeight: FontWeight.w600),
                        ),
                        if (_status!.nextWakeAt != null)
                          Text('Next wake: ${_formatTime(_status!.nextWakeAt!)}'),
                        if (_status!.lastWakeAt != null)
                          Text('Last wake: ${_formatTime(_status!.lastWakeAt!)}'),
                        if (_status!.lastDecision != null)
                          Text('Last decision: ${_status!.lastDecision}'),
                        if (_status!.consecutiveNoops > 0)
                          Text('Idle backoff: ${_status!.consecutiveNoops} no-ops'),
                        if (_status!.lastError != null)
                          Text(
                            'Error: ${_status!.lastError}',
                            style: const TextStyle(color: Colors.redAccent),
                          ),
                      ],
                    ),
                  ),
                const SizedBox(height: 16),
                SwitchListTile(
                  title: const Text('Enable adaptive heartbeat'),
                  subtitle: const Text(
                    'Wakes the agent on a bounded schedule to act autonomously.',
                  ),
                  value: _enabled,
                  onChanged: _busy
                      ? null
                      : (value) => setState(() => _enabled = value),
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: _minController,
                  decoration: const InputDecoration(
                    labelText: 'Min wake (seconds)',
                    border: OutlineInputBorder(),
                  ),
                  keyboardType: TextInputType.number,
                  enabled: !_busy,
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: _maxController,
                  decoration: const InputDecoration(
                    labelText: 'Max wake (seconds)',
                    border: OutlineInputBorder(),
                  ),
                  keyboardType: TextInputType.number,
                  enabled: !_busy,
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: _backoffController,
                  decoration: const InputDecoration(
                    labelText: 'Idle backoff factor (1.0 - 10.0)',
                    border: OutlineInputBorder(),
                  ),
                  keyboardType:
                      const TextInputType.numberWithOptions(decimal: true),
                  enabled: !_busy,
                ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Text(_error!, style: const TextStyle(color: Colors.redAccent)),
                ],
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: FilledButton.icon(
                        onPressed: _busy ? null : _save,
                        icon: _busy
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              )
                            : const Icon(Icons.save),
                        label: const Text('Save'),
                      ),
                    ),
                    const SizedBox(width: 12),
                    if (_enabled)
                      OutlinedButton.icon(
                        onPressed: _busy ? null : _wakeNow,
                        icon: const Icon(Icons.bolt),
                        label: const Text('Wake now'),
                      ),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  String _formatTime(DateTime t) {
    final local = t.toLocal();
    return '${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}';
  }
}