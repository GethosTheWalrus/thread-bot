import 'package:flutter/material.dart';
import 'package:threadbot/models/thread.dart';
import 'package:threadbot/services/api_service.dart';
import 'package:threadbot/services/autonomy_api.dart';
import 'package:threadbot/widgets/heartbeat_config_sheet.dart';

class ThreadParticipantManager extends StatefulWidget {
  final String threadId;
  final List<ThreadAgentSummary> participants;
  final int turnLimit;
  final bool embedded;
  final VoidCallback? onChanged;
  final ValueChanged<String>? onOpenConfig;
  const ThreadParticipantManager({
    super.key,
    required this.threadId,
    required this.participants,
    this.turnLimit = 0,
    this.embedded = false,
    this.onChanged,
    this.onOpenConfig,
  });

  @override
  State<ThreadParticipantManager> createState() =>
      _ThreadParticipantManagerState();
}

class _ThreadParticipantManagerState extends State<ThreadParticipantManager> {
  final _api = ApiService();
  final _autonomy = AutonomyApiService();
  late List<ThreadAgentSummary> _participants;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _participants = List.of(widget.participants);
  }

  Future<void> _reloadParticipants() async {
    try {
      final participants = await _api.getThreadAgents(widget.threadId);
      if (mounted) setState(() => _participants = participants);
    } catch (_) {
      // The acknowledged mutation remains reflected locally until the parent
      // thread refresh retries the roster request.
    }
  }

  void _applyActionLocally(ThreadAgentSummary selected, String action) {
    if (!mounted) return;
    setState(() {
      _participants = _participants.map((agent) {
        final status = agent.id == selected.id
            ? switch (action) {
                'active' => 'active',
                'paused' => 'paused',
                'archive' => 'archived',
                _ => agent.status,
              }
            : agent.status;
        return ThreadAgentSummary(
          id: agent.id,
          name: agent.name,
          status: status,
          executionMode: agent.executionMode,
          activeVersionId: agent.activeVersionId,
          mentionName: agent.mentionName,
          isModerator: action == 'moderator'
              ? agent.id == selected.id
              : agent.isModerator,
        );
      }).toList();
    });
  }

  Future<void> _add() async {
    final name = TextEditingController();
    final handle = TextEditingController();
    final instructions = TextEditingController();
    final result = await showDialog<List<String>>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Add participant'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: name,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Name'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: instructions,
              maxLines: 3,
              decoration: const InputDecoration(labelText: 'Instructions'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: handle,
              decoration: const InputDecoration(
                labelText: 'Mention handle',
                prefixText: '@',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              final n = name.text.trim();
              final h = handle.text.trim().replaceFirst(RegExp(r'^@'), '');
              if (n.isEmpty || h.isEmpty) return;
              Navigator.pop(context, [n, h, instructions.text.trim()]);
            },
            child: const Text('Add and activate'),
          ),
        ],
      ),
    );
    name.dispose();
    handle.dispose();
    instructions.dispose();
    if (result == null) return;
    if (_participants.any(
      (a) =>
          a.mentionName.toLowerCase() == result[1].toLowerCase() ||
          a.name.toLowerCase() == result[0].toLowerCase(),
    )) {
      if (mounted)
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('That participant already exists')),
        );
      return;
    }
    setState(() => _busy = true);
    try {
      final agent = await _autonomy.createAgent({
        'name': result[0],
        'handle': result[1],
        'thread_id': widget.threadId,
        'execution_mode': 'act',
      });
      try {
        await _autonomy.saveDraft(agent.id, {
          'optimistic_lock_version': 1,
          'schema_version': 1,
          'config': <String, dynamic>{},
          'prompt_template': result.length > 2 ? result[2] : '',
          'tool_selection': <String>[],
          'skill_selection': <String>[],
          'credential_bindings': <Map<String, dynamic>>[],
        });
        await _autonomy.activate(agent.id);
      } catch (e) {
        if (mounted)
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                'Participant added, but activation needs attention: $e',
              ),
            ),
          );
      }
      await _reloadParticipants();
      widget.onChanged?.call();
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not add participant: $e')),
        );
    }
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _lifecycle(ThreadAgentSummary agent, String action) async {
    setState(() => _busy = true);
    try {
      if (action == 'moderator') {
        await _api.setThreadModerator(widget.threadId, agent.id);
      } else if (action == 'archive') {
        await _api.threadAgentRequest(
          'DELETE',
          widget.threadId,
          agentId: agent.id,
        );
      } else {
        await _autonomy.lifecycle(agent.id, action == 'active');
      }
      _applyActionLocally(agent, action);
      await _reloadParticipants();
      widget.onChanged?.call();
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not update ${agent.name}: $e')),
        );
    }
    if (mounted) setState(() => _busy = false);
  }

  List<Widget> _buildContent(BuildContext context) => [
    Row(
      children: [
        const Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Agents in this thread',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w700),
              ),
              SizedBox(height: 3),
              Text(
                'Choose the moderator and manage each agent from one place.',
                style: TextStyle(fontSize: 12, color: Colors.white54),
              ),
            ],
          ),
        ),
        FilledButton.tonalIcon(
          onPressed: _busy ? null : _add,
          icon: const Icon(Icons.person_add_alt_1, size: 17),
          label: const Text('Add agent'),
        ),
      ],
    ),
    if (widget.turnLimit > 0) ...[
      const SizedBox(height: 8),
      Text(
        'Conversation turn limit: ${widget.turnLimit}',
        style: TextStyle(color: Colors.white.withValues(alpha: .55)),
      ),
    ],
    const SizedBox(height: 16),
    if (_participants.isEmpty)
      Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: .035),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: Colors.white10),
        ),
        child: const Text(
          'No agents are attached. Add one to turn this into an Agent Thread.',
          style: TextStyle(color: Colors.white60),
        ),
      ),
    ..._participants.map((agent) => _buildAgentCard(context, agent)),
  ];

  Widget _buildAgentCard(
    BuildContext context,
    ThreadAgentSummary agent,
  ) => Card(
    color: const Color(0xFF1D1D28),
    margin: const EdgeInsets.only(bottom: 10),
    child: Padding(
      padding: const EdgeInsets.fromLTRB(14, 12, 8, 10),
      child: Column(
        children: [
          Row(
            children: [
              CircleAvatar(
                radius: 19,
                child: Text(
                  agent.name.isEmpty ? '?' : agent.name[0].toUpperCase(),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Wrap(
                      spacing: 7,
                      runSpacing: 4,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        Text(
                          agent.name,
                          style: const TextStyle(fontWeight: FontWeight.w600),
                        ),
                        if (agent.isModerator)
                          const Chip(
                            visualDensity: VisualDensity.compact,
                            label: Text('Moderator'),
                          ),
                      ],
                    ),
                    Text(
                      '@${agent.mentionName} · ${agent.status} · ${agent.executionMode}',
                      style: const TextStyle(
                        fontSize: 12,
                        color: Colors.white54,
                      ),
                    ),
                  ],
                ),
              ),
              PopupMenuButton<String>(
                tooltip: 'Agent actions',
                onSelected: _busy
                    ? null
                    : (action) => _lifecycle(agent, action),
                itemBuilder: (_) => [
                  if (!agent.isModerator)
                    const PopupMenuItem(
                      value: 'moderator',
                      child: Text('Make moderator'),
                    ),
                  const PopupMenuItem(value: 'active', child: Text('Resume')),
                  const PopupMenuItem(value: 'paused', child: Text('Pause')),
                  const PopupMenuItem(value: 'archive', child: Text('Archive')),
                ],
              ),
            ],
          ),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                OutlinedButton.icon(
                  onPressed: widget.onOpenConfig == null
                      ? null
                      : () => widget.onOpenConfig!(agent.id),
                  icon: const Icon(Icons.dashboard_outlined, size: 16),
                  label: const Text('Details & settings'),
                ),
                OutlinedButton.icon(
                  onPressed: _busy
                      ? null
                      : () => HeartbeatConfigSheet.show(
                          context,
                          agentId: agent.id,
                          agentName: agent.name,
                          api: _autonomy,
                        ).then((_) => _reloadParticipants()),
                  icon: const Icon(Icons.favorite_border, size: 16),
                  label: const Text('Heartbeat'),
                ),
              ],
            ),
          ),
        ],
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final content = _buildContent(context);
    if (widget.embedded) {
      return ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
        children: content,
      );
    }
    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
        child: Column(
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
            const SizedBox(height: 22),
            ...content,
          ],
        ),
      ),
    );
  }
}
