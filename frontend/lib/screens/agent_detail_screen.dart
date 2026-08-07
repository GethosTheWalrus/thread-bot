import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:threadbot/models/autonomy.dart';
import 'package:threadbot/services/autonomy_api.dart';
import 'package:threadbot/widgets/agent_workspace_ui.dart';
import 'package:threadbot/widgets/heartbeat_config_sheet.dart';

class AgentDetailScreen extends StatefulWidget {
  final String id;
  final AutonomyApiService api;
  const AgentDetailScreen({super.key, required this.id, required this.api});
  @override
  State<AgentDetailScreen> createState() => _AgentDetailState();
}

class _AgentDetailState extends State<AgentDetailScreen> {
  Agent? agent;
  List<Run> runs = [];
  HeartbeatStatus? heartbeat;
  List<_Log> logs = [];
  bool loading = true;
  String? error;
  int tab = 0;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final a = await widget.api.agent(widget.id);
      var rs = <Run>[];
      HeartbeatStatus? hb;
      try {
        rs = (await widget.api.runs(widget.id)).items;
      } catch (_) {}
      try {
        hb = await widget.api.heartbeat(widget.id);
      } catch (_) {}
      final batches = await Future.wait(
        rs.take(12).map((r) async {
          try {
            final events = (await widget.api.events(r.id)).items;
            return events
                .map(
                  (e) => _Log(
                    e.createdAt ?? r.queuedAt,
                    r.id,
                    r.route,
                    e.type,
                    _summary(e.payload),
                  ),
                )
                .toList();
          } catch (_) {
            return <_Log>[];
          }
        }),
      );
      final all = batches.expand((batch) => batch).toList();
      all.sort(
        (a, b) => (b.time ?? DateTime(0)).compareTo(a.time ?? DateTime(0)),
      );
      if (mounted)
        setState(() {
          agent = a;
          runs = rs;
          heartbeat = hb;
          logs = all;
          loading = false;
        });
    } catch (e) {
      if (mounted)
        setState(() {
          error = '$e';
          loading = false;
        });
    }
  }

  String _summary(Map<String, dynamic> p) {
    for (final k in const [
      'display_content',
      'content',
      'message',
      'error',
      'reason',
      'summary',
      'decision',
      'status',
    ]) {
      final v = p[k];
      if (v is String && v.isNotEmpty) return v;
    }
    return p.keys
        .where((k) => !k.startsWith('_') && k != 'sequence')
        .take(3)
        .map((k) => '$k=${p[k]}')
        .join(', ');
  }

  @override
  Widget build(BuildContext context) {
    if (loading && agent == null)
      return const Scaffold(
        body: AgentStateView(
          icon: Icons.hourglass_top_rounded,
          title: 'Loading agent',
          message: 'Preparing its workspace…',
        ),
      );
    if (error != null && agent == null)
      return Scaffold(
        body: AgentStateView(
          icon: Icons.cloud_off_rounded,
          title: 'Could not load agent',
          message: error!,
          onAction: load,
        ),
      );
    final a = agent!;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1080),
            child: ListView(
              padding: const EdgeInsets.fromLTRB(24, 18, 24, 48),
              children: [
                _header(a),
                const SizedBox(height: 18),
                _tabs(),
                const SizedBox(height: 18),
                switch (tab) {
                  0 => _overview(a),
                  1 => _runs(),
                  2 => _activity(),
                  _ => _automation(),
                },
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _header(Agent a) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      AgentBreadcrumb(current: a.name, onBack: _backToAgents),
      const SizedBox(height: 18),
      Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: agentSurface,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: agentBorder),
        ),
        child: LayoutBuilder(
          builder: (_, c) => Wrap(
            spacing: 24,
            runSpacing: 18,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              SizedBox(
                width: c.maxWidth > 700 ? 360 : c.maxWidth,
                child: AgentIdentity(name: a.name, handle: a.handle),
              ),
              AgentStatusPill(a.status),
              if (a.isModerator)
                const Chip(
                  avatar: Icon(Icons.shield_outlined, size: 16),
                  label: Text('Moderator'),
                ),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  OutlinedButton.icon(
                    onPressed: a.threadId.isEmpty
                        ? null
                        : () => Navigator.pushNamed(
                            context,
                            '/thread/${a.threadId}',
                          ),
                    icon: const Icon(Icons.forum_outlined, size: 17),
                    label: const Text('Open thread'),
                  ),
                  const SizedBox(width: 8),
                  FilledButton.icon(
                    onPressed: () =>
                        Navigator.pushNamed(context, '/agents/${a.id}'),
                    icon: const Icon(Icons.tune_rounded, size: 17),
                    label: const Text('Configure'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    ],
  );
  Widget _tabs() => SingleChildScrollView(
    scrollDirection: Axis.horizontal,
    child: SegmentedButton<int>(
      segments: const [
        ButtonSegment(
          value: 0,
          label: Text('Overview'),
          icon: Icon(Icons.dashboard_outlined),
        ),
        ButtonSegment(
          value: 1,
          label: Text('Runs'),
          icon: Icon(Icons.play_circle_outline),
        ),
        ButtonSegment(
          value: 2,
          label: Text('Activity'),
          icon: Icon(Icons.timeline_rounded),
        ),
        ButtonSegment(
          value: 3,
          label: Text('Automation'),
          icon: Icon(Icons.schedule_rounded),
        ),
      ],
      selected: {tab},
      onSelectionChanged: (v) => setState(() => tab = v.first),
    ),
  );
  Widget _overview(Agent a) => Column(
    children: [
      Wrap(
        spacing: 10,
        runSpacing: 10,
        children: [
          AgentMetric(
            label: 'Runs shown',
            value: '${runs.length}',
            icon: Icons.play_arrow_rounded,
          ),
          AgentMetric(
            label: 'Concurrency',
            value: '${a.concurrencyLimit}',
            icon: Icons.speed_rounded,
          ),
          AgentMetric(
            label: 'Queue limit',
            value: '${a.queueLimit}',
            icon: Icons.inbox_outlined,
          ),
          AgentMetric(
            label: 'Version',
            value: a.activeVersionId == null ? 'Draft' : 'Active',
            icon: Icons.layers_outlined,
          ),
        ],
      ),
      const SizedBox(height: 16),
      AgentSection(
        title: 'Identity and ownership',
        description: 'The operating context this agent belongs to.',
        child: Wrap(
          spacing: 28,
          runSpacing: 14,
          children: [
            _fact(
              'Thread',
              a.threadTitle?.isNotEmpty == true ? a.threadTitle! : a.threadId,
            ),
            _fact('Role', a.isModerator ? 'Thread moderator' : 'Participant'),
            _fact('Created', a.createdAt == null ? '—' : _time(a.createdAt!)),
          ],
        ),
      ),
      if (a.description?.isNotEmpty == true)
        AgentSection(
          title: 'Purpose',
          child: Text(
            a.description!,
            style: const TextStyle(color: Colors.white70, height: 1.45),
          ),
        ),
    ],
  );
  Widget _runs() => runs.isEmpty
      ? const AgentStateView(
          title: 'No runs yet',
          message: 'Runs will appear here when this agent is activated.',
        )
      : Column(children: runs.map((r) => _runCard(r)).toList());
  Widget _runCard(Run r) => InkWell(
    onTap: () => Navigator.pushNamed(context, '/agent-runs/${r.id}'),
    borderRadius: BorderRadius.circular(14),
    child: AgentSection(
      title: _routeLabel(r.route),
      description: r.queuedAt == null
          ? 'Queued time unavailable'
          : _time(r.queuedAt!),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              AgentStatusPill(r.status),
              const Spacer(),
              const Icon(Icons.chevron_right_rounded, color: Colors.white38),
            ],
          ),
          if (r.outputSummary?.trim().isNotEmpty == true) ...[
            const SizedBox(height: 12),
            MarkdownBody(
              data: _preview(r.outputSummary!),
              shrinkWrap: true,
              styleSheet: _markdownStyle(),
            ),
          ],
        ],
      ),
    ),
  );
  Widget _activity() => logs.isEmpty
      ? const AgentStateView(
          title: 'No activity yet',
          message:
              'Events from agent runs will become a readable timeline here.',
        )
      : AgentSection(
          title: 'Recent activity',
          description: 'Select an event to inspect its run.',
          child: Column(
            children: logs
                .map(
                  (l) => InkWell(
                    onTap: () =>
                        Navigator.pushNamed(context, '/agent-runs/${l.runId}'),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 10),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Container(
                            width: 8,
                            height: 8,
                            margin: const EdgeInsets.only(top: 5),
                            decoration: const BoxDecoration(
                              color: agentViolet,
                              shape: BoxShape.circle,
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  l.type.replaceAll('_', ' '),
                                  style: const TextStyle(
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                                if (l.text.isNotEmpty)
                                  MarkdownBody(
                                    data: _preview(l.text, limit: 320),
                                    shrinkWrap: true,
                                    styleSheet: _markdownStyle(fontSize: 12),
                                  ),
                                Text(
                                  l.time == null ? '' : _time(l.time!),
                                  style: const TextStyle(
                                    color: Colors.white38,
                                    fontSize: 11,
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                )
                .toList(),
          ),
        );
  Widget _automation() {
    final h = heartbeat;
    if (h == null)
      return AgentStateView(
        icon: Icons.schedule_outlined,
        title: 'Automation is not configured',
        message: 'Set a heartbeat to let this agent check in on a cadence.',
        onAction: _configure,
        actionLabel: 'Configure automation',
      );
    return AgentSection(
      title: 'Heartbeat',
      description: h.enabled
          ? 'This agent can wake itself and evaluate its Thread.'
          : 'Heartbeat is currently off.',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              AgentStatusPill(h.operationalStatus),
              const SizedBox(width: 10),
              Text(
                h.statusLabel,
                style: const TextStyle(color: Colors.white60),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 28,
            runSpacing: 12,
            children: [
              _fact('Cadence', '${h.minWakeSeconds}s – ${h.maxWakeSeconds}s'),
              _fact('Backoff', '${h.idleBackoffFactor}x'),
              _fact(
                'Next wake',
                h.nextWakeAt == null ? '—' : _time(h.nextWakeAt!),
              ),
            ],
          ),
          const SizedBox(height: 18),
          Wrap(
            spacing: 10,
            children: [
              FilledButton.icon(
                onPressed: _configure,
                icon: const Icon(Icons.tune),
                label: const Text('Configure'),
              ),
              OutlinedButton.icon(
                onPressed: h.enabled
                    ? () async {
                        await widget.api.wakeHeartbeat(widget.id);
                        load();
                      }
                    : null,
                icon: const Icon(Icons.alarm),
                label: const Text('Wake now'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  void _configure() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      builder: (_) => HeartbeatConfigSheet(
        agentId: widget.id,
        agentName: agent?.name ?? 'Agent',
        api: widget.api,
      ),
    ).then((_) {
      load();
    });
  }

  void _backToAgents() {
    if (Navigator.canPop(context)) {
      Navigator.pop(context);
    } else {
      Navigator.pushReplacementNamed(context, '/agents-list');
    }
  }

  String _routeLabel(String route) {
    if (route.isEmpty) return 'Interactive run';
    final label = route.replaceAll('_', ' ');
    return '${label[0].toUpperCase()}${label.substring(1)} run';
  }

  String _preview(String value, {int limit = 600}) {
    final text = value.trim();
    return text.length <= limit ? text : '${text.substring(0, limit)}…';
  }

  MarkdownStyleSheet _markdownStyle({double fontSize = 13}) =>
      MarkdownStyleSheet(
        p: TextStyle(color: Colors.white70, fontSize: fontSize, height: 1.4),
        h1: TextStyle(
          color: Colors.white,
          fontSize: fontSize + 3,
          fontWeight: FontWeight.w700,
        ),
        h2: TextStyle(
          color: Colors.white,
          fontSize: fontSize + 2,
          fontWeight: FontWeight.w700,
        ),
        h3: TextStyle(
          color: Colors.white,
          fontSize: fontSize + 1,
          fontWeight: FontWeight.w700,
        ),
        strong: const TextStyle(
          color: Colors.white,
          fontWeight: FontWeight.w700,
        ),
        code: const TextStyle(
          color: Color(0xFFC4B5FD),
          backgroundColor: Color(0xFF111118),
        ),
        listBullet: const TextStyle(color: Color(0xFFA78BFA)),
      );

  Widget _fact(String label, String value) => SizedBox(
    width: 180,
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(color: Colors.white38, fontSize: 11),
        ),
        const SizedBox(height: 3),
        Text(
          value,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
      ],
    ),
  );
  String _time(DateTime d) {
    final x = DateTime.now().difference(d);
    if (x.inMinutes < 1) return 'just now';
    if (x.inHours < 1) return '${x.inMinutes}m ago';
    if (x.inDays < 1) return '${x.inHours}h ago';
    return '${x.inDays}d ago';
  }
}

class _Log {
  final DateTime? time;
  final String runId, route, type, text;
  _Log(this.time, this.runId, this.route, this.type, this.text);
}
