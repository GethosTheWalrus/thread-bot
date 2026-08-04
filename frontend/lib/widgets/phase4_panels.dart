import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:threadbot/models/autonomy.dart';
import 'package:threadbot/models/phase4.dart';
import 'package:threadbot/services/autonomy_api.dart';
import 'package:threadbot/services/phase4_api.dart';

String _safeJson(Object value) =>
    const JsonEncoder.withIndent('  ').convert(value);

Widget phase4Section(String title, Widget child) => Card(
  margin: const EdgeInsets.only(bottom: 16),
  child: Padding(
    padding: const EdgeInsets.all(18),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          title,
          style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
        ),
        const SizedBox(height: 12),
        child,
      ],
    ),
  ),
);

class ReplayPanel extends StatefulWidget {
  final Phase4ApiService api;
  final String runId;
  const ReplayPanel({super.key, required this.api, required this.runId});
  @override
  State<ReplayPanel> createState() => _ReplayPanelState();
}

class _ReplayPanelState extends State<ReplayPanel> {
  List<ReplaySession> sessions = [];
  bool loading = false;
  String? error;
  final Map<String, String> _replayKeys = {};
  Future<void> load() async {
    if (!mounted) return;
    setState(() => loading = true);
    try {
      final value = await widget.api.replays(widget.runId);
      if (mounted) setState(() => sessions = value);
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> run(String mode) async {
    final key = _replayKeys.putIfAbsent(
      mode,
      AutonomyApiService.newIdempotencyKey,
    );
    try {
      await widget.api.replay(widget.runId, mode: mode, idempotencyKey: key);
      _replayKeys[mode] = AutonomyApiService.newIdempotencyKey();
      await load();
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> exportReplay() async {
    try {
      final value = await widget.api.exportReplay(widget.runId);
      if (!mounted) return;
      showDialog<void>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Redacted replay export'),
          content: SizedBox(
            width: 560,
            child: SingleChildScrollView(
              child: SelectableText(_safeJson(value)),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('Close'),
            ),
          ],
        ),
      );
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  Widget build(BuildContext context) => phase4Section(
    'Replay',
    Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Recorded replay rebuilds stored events without model or external calls. Re-execution creates a new run and may differ because providers and systems vary; it is dry-run and effect-free by default.',
        ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 8,
          children: [
            FilledButton.icon(
              onPressed: loading ? null : () => run('recorded'),
              icon: const Icon(Icons.history),
              label: const Text('Recorded replay'),
            ),
            OutlinedButton.icon(
              onPressed: loading ? null : () => run('reexecution'),
              icon: const Icon(Icons.replay),
              label: const Text('Re-execute (dry-run)'),
            ),
            IconButton(
              onPressed: loading ? null : load,
              icon: const Icon(Icons.refresh),
            ),
            OutlinedButton.icon(
              onPressed: loading ? null : exportReplay,
              icon: const Icon(Icons.download_outlined),
              label: const Text('Export redacted'),
            ),
          ],
        ),
        if (error != null)
          Text(
            error!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        for (final replay in sessions)
          Card(
            margin: const EdgeInsets.only(top: 8),
            child: ExpansionTile(
              title: Text(
                '${replay.mode} • ${replay.effectFree ? 'effect-free' : 'server policy required'}',
              ),
              subtitle: Text(
                '${replay.timeline.length} timeline events${replay.mode == 'reexecution' ? ' • not deterministic' : ''}${replay.replayRunId == null ? '' : ' • replay run available'}',
              ),
              children: [
                for (final event in replay.timeline)
                  ListTile(
                    leading: const Icon(Icons.chevron_right),
                    title: Text(_timelineSummary(event)),
                    subtitle: Text(
                      event['sequence'] == null
                          ? 'Redacted details'
                          : 'Event ${event['sequence']} • redacted details',
                    ),
                  ),
                if (replay.replayRunId != null)
                  ListTile(
                    leading: const Icon(Icons.open_in_new),
                    title: Text('Replay run ${replay.replayRunId}'),
                    onTap: () => Navigator.pushNamed(
                      context,
                      '/agent-runs/${replay.replayRunId}',
                    ),
                  ),
                if (replay.comparison.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.all(12),
                    child: SelectableText(_safeJson(replay.comparison)),
                  ),
              ],
            ),
          ),
      ],
    ),
  );
}

String _timelineSummary(Map<String, dynamic> event) {
  final type = event['type']?.toString() ?? 'event';
  final summary = event['summary']?.toString();
  if (summary != null && summary.isNotEmpty) return '$type • $summary';
  final payload = event['payload'];
  if (payload is Map && payload.isNotEmpty) {
    return '$type • ${payload.length} redacted fields';
  }
  final status = event['status']?.toString();
  return status == null || status.isEmpty ? type : '$type • $status';
}

class ForecastPanel extends StatelessWidget {
  final ForecastSnapshot? forecast;
  const ForecastPanel({super.key, required this.forecast});
  @override
  Widget build(BuildContext context) => phase4Section(
    'Advanced forecast',
    forecast == null
        ? const Text('Forecast unavailable')
        : Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '${forecast!.horizonHours} hour horizon • confidence: ${forecast!.confidence}',
              ),
              for (final entry in forecast!.metrics.entries)
                ListTile(
                  dense: true,
                  title: Text(entry.key),
                  subtitle: Text(
                    entry.value.entries
                        .map((x) => '${x.key}: ${x.value ?? '—'}')
                        .join(' • '),
                  ),
                ),
              const Text(
                'Assumptions',
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
              for (final assumption in forecast!.assumptions)
                Text('• $assumption'),
              const SizedBox(height: 4),
              const Text(
                'Forecasts inform operators and do not change budgets or limits.',
              ),
            ],
          ),
  );
}

class CanaryPanel extends StatefulWidget {
  final Phase4ApiService api;
  final Agent agent;
  final List<Version> versions;
  const CanaryPanel({
    super.key,
    required this.api,
    required this.agent,
    required this.versions,
  });
  @override
  State<CanaryPanel> createState() => _CanaryPanelState();
}

class _CanaryPanelState extends State<CanaryPanel> {
  List<CanaryDeployment> items = [];
  String? selected;
  bool busy = false;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final value = await widget.api.canaries(widget.agent.id);
      if (mounted) setState(() => items = value);
    } catch (_) {}
  }

  Future<void> create() async {
    if (selected == null) return;
    setState(() => busy = true);
    try {
      await widget.api.createCanary(widget.agent.id, selected!);
      await load();
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> decide(CanaryDeployment item, String action) async {
    final reason = TextEditingController();
    try {
      final ok = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: Text(
            '${action == 'promote' ? 'Promote' : 'Rollback'} canary?',
          ),
          content: TextField(
            controller: reason,
            decoration: const InputDecoration(labelText: 'Audited reason'),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(c, true),
              child: const Text('Confirm'),
            ),
          ],
        ),
      );
      if (ok == true && reason.text.trim().isNotEmpty) {
        await widget.api.decideCanary(
          item.id,
          action,
          reason: reason.text.trim(),
          expectedVersion: item.version,
        );
        await load();
      }
    } catch (e) {
      if (e is ApiException && e.conflict) {
        await load();
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(
              content: Text('Canary changed elsewhere; reloaded.'),
            ),
          );
        }
        return;
      }
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
      }
    } finally {
      reason.dispose();
    }
  }

  Future<void> compare(CanaryDeployment item) async {
    try {
      final values = await widget.api.comparisons(item.id);
      if (!mounted) return;
      showDialog<void>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Stable / candidate comparison'),
          content: SizedBox(
            width: 560,
            child: values.isEmpty
                ? const Text('No comparison samples yet.')
                : ListView(
                    shrinkWrap: true,
                    children: [
                      for (final value in values)
                        SelectableText(_safeJson(value)),
                    ],
                  ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('Close'),
            ),
          ],
        ),
      );
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  @override
  Widget build(BuildContext context) => phase4Section(
    'Canary / shadow rollout',
    Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          'Shadow effects are blocked server-side: no notifications, handoffs, mutations, or Reachy operations. Promotion and rollback are explicit and audited; active runs stay pinned.',
        ),
        LayoutBuilder(
          builder: (context, constraints) {
            final selector = DropdownButtonFormField<String>(
              initialValue: selected,
              hint: const Text('Candidate version'),
              items: [
                for (final v in widget.versions)
                  DropdownMenuItem(
                    value: v.id,
                    child: Text('Version ${v.version}'),
                  ),
              ],
              onChanged: (v) => setState(() => selected = v),
            );
            final button = FilledButton(
              onPressed: busy || selected == null ? null : create,
              child: const Text('Start canary'),
            );
            return constraints.maxWidth < 560
                ? Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [selector, const SizedBox(height: 8), button],
                  )
                : Row(
                    children: [
                      Expanded(child: selector),
                      const SizedBox(width: 8),
                      button,
                    ],
                  );
          },
        ),
        for (final item in items)
          Card(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  ListTile(
                    title: Text(
                      '${item.status} • candidate ${item.candidateVersionId}',
                    ),
                    subtitle: Text(
                      'Stable ${item.stableVersionId} • deployment v${item.version}',
                    ),
                  ),
                  Wrap(
                    spacing: 4,
                    children: [
                      TextButton(
                        onPressed: () => compare(item),
                        child: const Text('Compare'),
                      ),
                      TextButton(
                        onPressed:
                            item.status == 'active' || item.status == 'paused'
                            ? () => decide(item, 'rollback')
                            : null,
                        child: const Text('Rollback'),
                      ),
                      FilledButton(
                        onPressed:
                            item.status == 'active' || item.status == 'paused'
                            ? () => decide(item, 'promote')
                            : null,
                        child: const Text('Promote'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
      ],
    ),
  );
}

class Phase4OperationsPanel extends StatefulWidget {
  final Phase4ApiService api;
  const Phase4OperationsPanel({super.key, required this.api});
  @override
  State<Phase4OperationsPanel> createState() => _Phase4OperationsPanelState();
}

class _Phase4OperationsPanelState extends State<Phase4OperationsPanel> {
  SloSnapshot? snapshot;
  List<Map<String, dynamic>> alerts = [];
  String queue = 'threadbot-agent';
  String? error;
  String? success;
  bool loading = false, queueBusy = false;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    if (!mounted) return;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final value = await Future.wait([widget.api.slo(), widget.api.alerts()]);
      if (mounted)
        setState(() {
          snapshot = value[0] as SloSnapshot;
          alerts = value[1] as List<Map<String, dynamic>>;
        });
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> queueAction(String state) async {
    setState(() {
      queueBusy = true;
      success = null;
      error = null;
    });
    try {
      await widget.api.queueState(queue, state);
      if (mounted) setState(() => success = '$queue is $state');
      await load();
    } catch (e) {
      if (mounted) setState(() => error = '$e');
      if (mounted)
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => queueBusy = false);
    }
  }

  Future<void> recover(String operation) async {
    final id = TextEditingController();
    try {
      final ok = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: Text(operation.replaceAll('_', ' ')),
          content: TextField(
            controller: id,
            decoration: const InputDecoration(labelText: 'Resource ID'),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(c),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(c, true),
              child: const Text('Submit'),
            ),
          ],
        ),
      );
      if (ok == true && id.text.trim().isNotEmpty) {
        await widget.api.recover(operation, id.text.trim());
        await load();
      }
    } finally {
      id.dispose();
    }
  }

  @override
  Widget build(BuildContext context) => phase4Section(
    'SLO / observability and recovery',
    Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (snapshot == null)
          loading
              ? const CircularProgressIndicator()
              : Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (error != null)
                      Text(
                        error!,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    OutlinedButton.icon(
                      onPressed: load,
                      icon: const Icon(Icons.refresh),
                      label: const Text('Retry'),
                    ),
                  ],
                )
        else
          Wrap(
            spacing: 12,
            runSpacing: 8,
            children: [
              Chip(label: Text('Runs ${snapshot!.runsTotal}')),
              Chip(label: Text('Queue ${snapshot!.queueDepth}')),
              Chip(label: Text('Dead letters ${snapshot!.deadLetters}')),
            ],
          ),
        if (snapshot?.alerts.any((x) => x.isNotEmpty) == true)
          const ListTile(
            leading: Icon(Icons.warning_amber),
            title: Text('SLO alerts active'),
            subtitle: Text('Review backlog and dead-letter recovery.'),
          ),
        for (final alert in alerts)
          ListTile(
            title: Text(alert['alert_key']?.toString() ?? 'Alert'),
            subtitle: Text(
              '${alert['metric'] ?? ''} • ${alert['status'] ?? ''}',
            ),
          ),
        if (success != null)
          Text(
            success!,
            style: TextStyle(color: Theme.of(context).colorScheme.primary),
          ),
        if (error != null && snapshot != null)
          Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 8,
            children: [
              Text(
                error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
              OutlinedButton.icon(
                onPressed: loading ? null : load,
                icon: const Icon(Icons.refresh),
                label: const Text('Retry'),
              ),
            ],
          ),
        DropdownButtonFormField<String>(
          initialValue: queue,
          items: const [
            DropdownMenuItem(
              value: 'threadbot-agent',
              child: Text('threadbot-agent'),
            ),
            DropdownMenuItem(
              value: 'threadbot-connectors',
              child: Text('threadbot-connectors'),
            ),
            DropdownMenuItem(
              value: 'threadbot-notifications',
              child: Text('threadbot-notifications'),
            ),
          ],
          onChanged: (v) {
            if (v != null) setState(() => queue = v);
          },
          decoration: const InputDecoration(labelText: 'Queue'),
        ),
        Wrap(
          spacing: 8,
          children: [
            OutlinedButton(
              onPressed: queueBusy ? null : () => queueAction('paused'),
              child: const Text('Pause queue'),
            ),
            OutlinedButton(
              onPressed: queueBusy ? null : () => queueAction('draining'),
              child: const Text('Drain queue'),
            ),
            OutlinedButton(
              onPressed: queueBusy ? null : () => queueAction('running'),
              child: const Text('Resume queue'),
            ),
          ],
        ),
        Wrap(
          spacing: 8,
          children: [
            TextButton(
              onPressed: () => recover('retry_dead_letter'),
              child: const Text('Retry dead letter'),
            ),
            TextButton(
              onPressed: () => recover('reconcile_action'),
              child: const Text('Reconcile action'),
            ),
            TextButton(
              onPressed: () => recover('expire_approval'),
              child: const Text('Expire approval'),
            ),
            TextButton(
              onPressed: () => recover('rollback_version'),
              child: const Text('Rollback version'),
            ),
          ],
        ),
      ],
    ),
  );
}
