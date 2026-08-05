import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:threadbot/models/autonomy.dart';
import 'package:threadbot/services/autonomy_api.dart';
import 'package:threadbot/widgets/heartbeat_config_sheet.dart';

class AgentDetailScreen extends StatefulWidget {
  final String id;
  final AutonomyApiService api;
  const AgentDetailScreen({super.key, required this.id, required this.api});

  @override
  State<AgentDetailScreen> createState() => _AgentDetailScreenState();
}

class _AgentDetailScreenState extends State<AgentDetailScreen>
    with SingleTickerProviderStateMixin {
  late TabController _tabController;
  Agent? _agent;
  List<Run> _runs = [];
  HeartbeatStatus? _heartbeat;
  List<_LogEntry> _logs = [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 4, vsync: this);
    _load();
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final agent = await widget.api.agent(widget.id);
      List<Run> runs = [];
      HeartbeatStatus? hb;
      try {
        final page = await widget.api.runs(widget.id);
        runs = page.items;
      } catch (_) {}
      try {
        hb = await widget.api.heartbeat(widget.id);
      } catch (_) {}
      final batches = await Future.wait(
        runs.take(12).map((run) async {
          try {
            final events = await widget.api.events(run.id);
            return events.items
                .map(
                  (e) => _LogEntry(
                    timestamp: e.createdAt ?? run.queuedAt,
                    runId: run.id,
                    runRoute: run.route,
                    eventType: e.type,
                    summary: _eventSummary(e.payload),
                  ),
                )
                .toList();
          } catch (_) {
            return <_LogEntry>[];
          }
        }),
      );
      final logs = batches.expand((items) => items).toList();
      logs.sort((a, b) {
        final ta = a.timestamp;
        final tb = b.timestamp;
        if (ta == null && tb == null) return 0;
        if (ta == null) return 1;
        if (tb == null) return -1;
        return tb.compareTo(ta);
      });
      if (mounted) {
        setState(() {
          _agent = agent;
          _runs = runs;
          _heartbeat = hb;
          _logs = logs;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
      if (mounted) setState(() => _loading = false);
    }
  }

  String _eventSummary(Map<String, dynamic> payload) {
    final content =
        payload['display_content'] ??
        payload['content'] ??
        payload['message'] ??
        payload['error'] ??
        payload['reason'] ??
        payload['summary'] ??
        payload['decision'] ??
        payload['status'];
    if (content is String && content.isNotEmpty) return content;
    final keys = payload.keys.where(
      (k) => !k.startsWith('_') && k != 'sequence',
    );
    if (keys.isEmpty) return '';
    return keys.take(3).map((k) => '$k=${payload[k]}').join(', ');
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0F0A1A),
      appBar: AppBar(
        title: Text(_agent?.name ?? 'Agent'),
        backgroundColor: const Color(0xFF15101F),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loading ? null : _load,
          ),
        ],
        bottom: TabBar(
          controller: _tabController,
          indicatorColor: const Color(0xFF8B5CF6),
          labelColor: const Color(0xFFC4B5FD),
          unselectedLabelColor: Colors.white38,
          tabs: const [
            Tab(text: 'Overview'),
            Tab(text: 'Runs'),
            Tab(text: 'Logs'),
            Tab(text: 'Heartbeat'),
          ],
        ),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
          ? Center(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(_error!, style: const TextStyle(color: Colors.red)),
                  const SizedBox(height: 12),
                  TextButton(onPressed: _load, child: const Text('Retry')),
                ],
              ),
            )
          : TabBarView(
              controller: _tabController,
              children: [
                _constrained(_buildOverview()),
                _constrained(_buildRuns()),
                _constrained(_buildLogs()),
                _constrained(_buildHeartbeat()),
              ],
            ),
    );
  }

  Widget _buildOverview() {
    final a = _agent;
    if (a == null) return const Center(child: Text('No agent data'));
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _buildInfoRow('Name', a.name),
        _buildInfoRow('Handle', '@${a.handle}'),
        _buildInfoRow('Status', a.status),
        _buildInfoRow('Moderator', a.isModerator ? 'Yes' : 'No'),
        if (a.activeVersionId != null)
          _buildInfoRow('Active version', a.activeVersionId!),
        _buildInfoRow('Concurrency', '${a.concurrencyLimit}'),
        _buildInfoRow('Queue limit', '${a.queueLimit}'),
        if (a.createdAt != null)
          _buildInfoRow('Created', _formatTime(a.createdAt!)),
        if (a.updatedAt != null)
          _buildInfoRow('Updated', _formatTime(a.updatedAt!)),
        const SizedBox(height: 16),
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            onPressed: () => Navigator.pushNamed(context, '/agents/${a.id}'),
            icon: const Icon(Icons.edit, size: 18),
            label: const Text('Open editor'),
          ),
        ),
        const SizedBox(height: 8),
        SizedBox(
          width: double.infinity,
          child: OutlinedButton.icon(
            onPressed: a.threadId.isEmpty
                ? null
                : () => Navigator.pushNamed(context, '/thread/${a.threadId}'),
            icon: const Icon(Icons.chat, size: 18),
            label: const Text('Open thread'),
          ),
        ),
      ],
    );
  }

  Widget _buildRuns() {
    if (_runs.isEmpty) {
      return const Center(
        child: Text('No runs yet', style: TextStyle(color: Colors.white54)),
      );
    }
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: _runs.length,
      itemBuilder: (_, i) {
        final run = _runs[i];
        final statusColor = _runStatusColor(run.status);
        return Card(
          color: const Color(0xFF211B35),
          margin: const EdgeInsets.only(bottom: 8),
          child: ListTile(
            contentPadding: const EdgeInsets.symmetric(
              horizontal: 16,
              vertical: 6,
            ),
            title: Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 2,
                  ),
                  decoration: BoxDecoration(
                    color: statusColor.withValues(alpha: 0.2),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    run.status.replaceAll('_', ' '),
                    style: TextStyle(fontSize: 11, color: statusColor),
                  ),
                ),
                if (run.route.isNotEmpty) ...[
                  const SizedBox(width: 6),
                  Text(
                    run.route,
                    style: const TextStyle(fontSize: 11, color: Colors.white38),
                  ),
                ],
              ],
            ),
            subtitle: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (run.outputSummary?.isNotEmpty == true) ...[
                  const SizedBox(height: 4),
                  MarkdownBody(
                    data: _markdownPreview(run.outputSummary!),
                    shrinkWrap: true,
                    styleSheet: _previewMarkdownStyle(),
                  ),
                ],
                const SizedBox(height: 2),
                Text(
                  run.queuedAt != null ? _formatTime(run.queuedAt!) : '',
                  style: const TextStyle(fontSize: 11, color: Colors.white38),
                ),
              ],
            ),
            trailing: const Icon(
              Icons.chevron_right_rounded,
              color: Colors.white30,
            ),
            onTap: () => Navigator.pushNamed(context, '/agent-runs/${run.id}'),
          ),
        );
      },
    );
  }

  Widget _buildLogs() {
    if (_logs.isEmpty) {
      return const Center(
        child: Text(
          'No activity logs yet',
          style: TextStyle(color: Colors.white54),
        ),
      );
    }
    return ListView.builder(
      padding: const EdgeInsets.all(16),
      itemCount: _logs.length,
      itemBuilder: (_, i) => _buildLogEntry(_logs[i]),
    );
  }

  Widget _buildLogEntry(_LogEntry entry) {
    final typeColor = _eventTypeColor(entry.eventType);
    return Card(
      color: const Color(0xFF1A1428),
      margin: const EdgeInsets.only(bottom: 6),
      child: InkWell(
        onTap: () => Navigator.pushNamed(context, '/agent-runs/${entry.runId}'),
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 3,
                height: 36,
                margin: const EdgeInsets.only(top: 2),
                decoration: BoxDecoration(
                  color: typeColor,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Flexible(
                          child: Text(
                            entry.eventType.replaceAll('_', ' '),
                            style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                              color: typeColor,
                            ),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        if (entry.runRoute.isNotEmpty) ...[
                          const SizedBox(width: 6),
                          Text(
                            entry.runRoute,
                            style: const TextStyle(
                              fontSize: 10,
                              color: Colors.white38,
                            ),
                          ),
                        ],
                      ],
                    ),
                    if (entry.summary.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      MarkdownBody(
                        data: _markdownPreview(entry.summary),
                        shrinkWrap: true,
                        styleSheet: _previewMarkdownStyle(fontSize: 11),
                      ),
                    ],
                    const SizedBox(height: 2),
                    Text(
                      entry.timestamp != null
                          ? _formatTime(entry.timestamp!)
                          : '',
                      style: const TextStyle(
                        fontSize: 10,
                        color: Colors.white30,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  String _markdownPreview(String value) {
    final trimmed = value.trim();
    if (trimmed.length <= 600) return trimmed;
    return '${trimmed.substring(0, 600)}…';
  }

  MarkdownStyleSheet _previewMarkdownStyle({
    double fontSize = 12,
  }) => MarkdownStyleSheet(
    p: TextStyle(fontSize: fontSize, color: Colors.white70, height: 1.35),
    h1: TextStyle(
      fontSize: fontSize + 2,
      color: Colors.white,
      fontWeight: FontWeight.w700,
    ),
    h2: TextStyle(
      fontSize: fontSize + 1,
      color: Colors.white,
      fontWeight: FontWeight.w700,
    ),
    h3: TextStyle(
      fontSize: fontSize,
      color: Colors.white,
      fontWeight: FontWeight.w700,
    ),
    listBullet: TextStyle(fontSize: fontSize, color: const Color(0xFFC4B5FD)),
    strong: const TextStyle(fontWeight: FontWeight.w700, color: Colors.white),
    em: const TextStyle(fontStyle: FontStyle.italic, color: Colors.white70),
    code: TextStyle(
      fontSize: fontSize - 1,
      color: const Color(0xFFC4B5FD),
      backgroundColor: const Color(0xFF111018),
    ),
    blockquoteDecoration: const BoxDecoration(
      border: Border(left: BorderSide(color: Color(0xFF8B5CF6), width: 3)),
    ),
    blockquotePadding: const EdgeInsets.only(left: 10),
    blockquote: TextStyle(fontSize: fontSize, color: Colors.white60),
  );

  Widget _buildHeartbeat() {
    final hb = _heartbeat;
    if (hb == null) {
      return const Center(
        child: Text(
          'No heartbeat configured',
          style: TextStyle(color: Colors.white54),
        ),
      );
    }
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _buildInfoRow('Enabled', hb.enabled ? 'Yes' : 'No'),
        _buildInfoRow('Status', hb.operationalStatus.replaceAll('_', ' ')),
        _buildInfoRow('Min wake', '${hb.minWakeSeconds}s'),
        _buildInfoRow('Max wake', '${hb.maxWakeSeconds}s'),
        _buildInfoRow('Backoff', '${hb.idleBackoffFactor}x'),
        _buildInfoRow('Revision', '${hb.revision}'),
        if (hb.lastWakeAt != null)
          _buildInfoRow('Last wake', _formatTime(hb.lastWakeAt!)),
        if (hb.lastCompletedAt != null)
          _buildInfoRow('Last completed', _formatTime(hb.lastCompletedAt!)),
        if (hb.nextWakeAt != null)
          _buildInfoRow('Next wake', _formatTime(hb.nextWakeAt!)),
        if (hb.lastDecision != null)
          _buildInfoRow('Last decision', hb.lastDecision!),
        _buildInfoRow('Consecutive no-ops', '${hb.consecutiveNoops}'),
        if (hb.lastError != null) _buildInfoRow('Last error', hb.lastError!),
        const SizedBox(height: 16),
        LayoutBuilder(
          builder: (_, constraints) => Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              SizedBox(
                width: constraints.maxWidth < 520
                    ? constraints.maxWidth
                    : (constraints.maxWidth - 8) / 2,
                child: FilledButton.icon(
                  onPressed: () {
                    showModalBottomSheet(
                      context: context,
                      isScrollControlled: true,
                      builder: (_) => HeartbeatConfigSheet(
                        agentId: widget.id,
                        agentName: _agent?.name ?? 'Agent',
                        api: widget.api,
                      ),
                    ).then((_) => _load());
                  },
                  icon: const Icon(Icons.edit, size: 18),
                  label: const Text('Configure'),
                ),
              ),
              SizedBox(
                width: constraints.maxWidth < 520
                    ? constraints.maxWidth
                    : (constraints.maxWidth - 8) / 2,
                child: OutlinedButton.icon(
                  onPressed: hb.enabled
                      ? () async {
                          try {
                            await widget.api.wakeHeartbeat(widget.id);
                            if (mounted) {
                              ScaffoldMessenger.of(context).showSnackBar(
                                const SnackBar(
                                  content: Text('Wake signal sent'),
                                ),
                              );
                              _load();
                            }
                          } catch (e) {
                            if (mounted) {
                              ScaffoldMessenger.of(
                                context,
                              ).showSnackBar(SnackBar(content: Text('$e')));
                            }
                          }
                        }
                      : null,
                  icon: const Icon(Icons.alarm, size: 18),
                  label: const Text('Wake now'),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _constrained(Widget child) => Align(
    alignment: Alignment.topCenter,
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 900),
      child: child,
    ),
  );

  Widget _buildInfoRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 120,
            child: Text(
              label,
              style: const TextStyle(fontSize: 13, color: Colors.white54),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: const TextStyle(fontSize: 13, color: Colors.white),
            ),
          ),
        ],
      ),
    );
  }

  Color _runStatusColor(String status) {
    switch (status) {
      case 'succeeded':
        return Colors.green;
      case 'running':
        return const Color(0xFFC4B5FD);
      case 'queued':
        return Colors.blue;
      case 'waiting_approval':
        return Colors.amber;
      case 'failed':
      case 'suppressed':
      case 'cancelled':
        return Colors.red;
      case 'exhausted':
      case 'timed_out':
        return Colors.orange;
      default:
        return Colors.white54;
    }
  }

  Color _eventTypeColor(String type) {
    if (type.contains('heartbeat') || type.contains('wake')) return Colors.teal;
    if (type.contains('queued')) return Colors.blue;
    if (type.contains('started') || type.contains('running'))
      return const Color(0xFFC4B5FD);
    if (type.contains('planning') || type.contains('plan')) return Colors.cyan;
    if (type.contains('action') || type.contains('tool')) return Colors.purple;
    if (type.contains('approval')) return Colors.amber;
    if (type.contains('finalized') ||
        type.contains('completed') ||
        type.contains('succeeded'))
      return Colors.green;
    if (type.contains('failed') ||
        type.contains('error') ||
        type.contains('cancelled'))
      return Colors.red;
    if (type.contains('no_op') || type.contains('noop')) return Colors.grey;
    return Colors.white54;
  }

  String _formatTime(DateTime dt) {
    final now = DateTime.now();
    final diff = now.difference(dt);
    if (diff.inMinutes < 1) return 'just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
    if (diff.inHours < 24) return '${diff.inHours}h ago';
    if (diff.inDays < 7) return '${diff.inDays}d ago';
    return '${dt.month}/${dt.day} ${dt.hour}:${dt.minute.toString().padLeft(2, '0')}';
  }
}

class _LogEntry {
  final DateTime? timestamp;
  final String runId;
  final String runRoute;
  final String eventType;
  final String summary;

  _LogEntry({
    this.timestamp,
    required this.runId,
    required this.runRoute,
    required this.eventType,
    required this.summary,
  });
}
