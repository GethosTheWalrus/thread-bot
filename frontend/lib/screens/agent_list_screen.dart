import 'dart:async';

import 'package:flutter/material.dart';
import 'package:threadbot/models/autonomy.dart';
import 'package:threadbot/services/autonomy_api.dart';

class AgentListScreen extends StatefulWidget {
  final AutonomyApiService api;
  const AgentListScreen({super.key, required this.api});

  @override
  State<AgentListScreen> createState() => _AgentListScreenState();
}

class _AgentListScreenState extends State<AgentListScreen> {
  List<Agent> _agents = [];
  bool _loading = true;
  bool _loadingMore = false;
  String? _error;
  String? _nextCursor;
  final _searchController = TextEditingController();
  Timer? _searchDebounce;
  String _status = 'all';
  String _role = 'all';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _searchDebounce?.cancel();
    _searchController.dispose();
    super.dispose();
  }

  void _searchChanged(String _) {
    _searchDebounce?.cancel();
    _searchDebounce = Timer(const Duration(milliseconds: 300), _load);
  }

  bool? get _moderatorFilter => switch (_role) {
    'moderator' => true,
    'participant' => false,
    _ => null,
  };

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final page = await widget.api.agents(
        limit: 50,
        query: _searchController.text,
        status: _status,
        moderator: _moderatorFilter,
      );
      if (mounted) {
        setState(() {
          _agents = page.items;
          _nextCursor = page.nextCursor;
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _loadMore() async {
    final cursor = _nextCursor;
    if (cursor == null || _loadingMore) return;
    setState(() => _loadingMore = true);
    try {
      final page = await widget.api.agents(
        cursor: cursor,
        limit: 50,
        query: _searchController.text,
        status: _status,
        moderator: _moderatorFilter,
      );
      if (mounted) {
        setState(() {
          final known = _agents.map((agent) => agent.id).toSet();
          _agents.addAll(page.items.where((agent) => known.add(agent.id)));
          _nextCursor = page.nextCursor;
        });
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not load more agents: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0F0A1A),
      appBar: AppBar(
        title: const Text('Agents'),
        backgroundColor: const Color(0xFF15101F),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loading ? null : _load,
          ),
        ],
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
          : Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 900),
                child: ListView.builder(
                  padding: const EdgeInsets.fromLTRB(16, 20, 16, 40),
                  itemCount:
                      _agents.length +
                      2 +
                      ((_agents.isEmpty || _nextCursor != null) ? 1 : 0),
                  itemBuilder: (_, i) {
                    if (i == 0) return _buildControls();
                    if (i == 1) return _buildSummary();
                    final agentIndex = i - 2;
                    if (agentIndex < _agents.length) {
                      return _buildAgentCard(_agents[agentIndex]);
                    }
                    if (_agents.isEmpty) {
                      return const Padding(
                        padding: EdgeInsets.symmetric(vertical: 64),
                        child: Center(
                          child: Text(
                            'No agents match these filters',
                            style: TextStyle(color: Colors.white54),
                          ),
                        ),
                      );
                    }
                    return Padding(
                      padding: const EdgeInsets.only(top: 8),
                      child: OutlinedButton.icon(
                        onPressed: _loadingMore ? null : _loadMore,
                        icon: _loadingMore
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Icon(Icons.expand_more_rounded),
                        label: Text(_loadingMore ? 'Loading...' : 'Load more'),
                      ),
                    );
                  },
                ),
              ),
            ),
    );
  }

  Widget _buildControls() => Padding(
    padding: const EdgeInsets.only(bottom: 18),
    child: Column(
      children: [
        TextField(
          controller: _searchController,
          onChanged: _searchChanged,
          decoration: InputDecoration(
            hintText: 'Search agents, handles, or threads',
            prefixIcon: const Icon(Icons.search_rounded),
            suffixIcon: _searchController.text.isEmpty
                ? null
                : IconButton(
                    tooltip: 'Clear search',
                    onPressed: () {
                      _searchController.clear();
                      _load();
                    },
                    icon: const Icon(Icons.close_rounded),
                  ),
            filled: true,
            fillColor: const Color(0xFF1A1428),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(12),
              borderSide: BorderSide.none,
            ),
          ),
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            Expanded(
              child: DropdownButtonFormField<String>(
                initialValue: _status,
                decoration: const InputDecoration(
                  labelText: 'Status',
                  isDense: true,
                ),
                items: const [
                  DropdownMenuItem(value: 'all', child: Text('All statuses')),
                  DropdownMenuItem(value: 'active', child: Text('Active')),
                  DropdownMenuItem(value: 'draft', child: Text('Draft')),
                  DropdownMenuItem(value: 'paused', child: Text('Paused')),
                  DropdownMenuItem(value: 'archived', child: Text('Archived')),
                ],
                onChanged: (value) {
                  if (value == null || value == _status) return;
                  setState(() => _status = value);
                  _load();
                },
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: DropdownButtonFormField<String>(
                initialValue: _role,
                decoration: const InputDecoration(
                  labelText: 'Thread role',
                  isDense: true,
                ),
                items: const [
                  DropdownMenuItem(value: 'all', child: Text('All roles')),
                  DropdownMenuItem(
                    value: 'moderator',
                    child: Text('Moderators'),
                  ),
                  DropdownMenuItem(
                    value: 'participant',
                    child: Text('Participants'),
                  ),
                ],
                onChanged: (value) {
                  if (value == null || value == _role) return;
                  setState(() => _role = value);
                  _load();
                },
              ),
            ),
          ],
        ),
      ],
    ),
  );

  Widget _buildSummary() {
    final active = _agents.where((agent) => agent.status == 'active').length;
    final paused = _agents.where((agent) => agent.status == 'paused').length;
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Row(
        children: [
          Text(
            '${_agents.length} agent${_agents.length == 1 ? '' : 's'}',
            style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w700),
          ),
          const Spacer(),
          _summaryChip('$active active', Colors.green),
          if (paused > 0) ...[
            const SizedBox(width: 8),
            _summaryChip('$paused paused', Colors.blue),
          ],
        ],
      ),
    );
  }

  Widget _summaryChip(String label, Color color) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
    decoration: BoxDecoration(
      color: color.withValues(alpha: 0.14),
      borderRadius: BorderRadius.circular(20),
    ),
    child: Text(label, style: TextStyle(fontSize: 11, color: color)),
  );

  Widget _buildAgentCard(Agent agent) {
    final statusColor = _statusColor(agent.status);
    return Semantics(
      button: true,
      label: 'Open ${agent.name}, ${agent.status}',
      child: Card(
        color: const Color(0xFF211B35),
        margin: const EdgeInsets.only(bottom: 8),
        child: ListTile(
          contentPadding: const EdgeInsets.symmetric(
            horizontal: 16,
            vertical: 8,
          ),
          leading: CircleAvatar(
            backgroundColor: const Color(0xFF8B5CF6).withValues(alpha: 0.2),
            child: Text(
              agent.name.isNotEmpty ? agent.name[0].toUpperCase() : '?',
              style: const TextStyle(color: Color(0xFFC4B5FD)),
            ),
          ),
          title: Row(
            children: [
              Flexible(
                child: Text(
                  agent.name,
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (agent.handle.isNotEmpty) ...[
                const SizedBox(width: 8),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 6,
                    vertical: 2,
                  ),
                  decoration: BoxDecoration(
                    color: const Color(0xFF8B5CF6).withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Text(
                    '@${agent.handle}',
                    style: const TextStyle(
                      fontSize: 11,
                      color: Color(0xFFC4B5FD),
                    ),
                  ),
                ),
              ],
            ],
          ),
          subtitle: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 5),
              Row(
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
                      agent.status,
                      style: TextStyle(fontSize: 11, color: statusColor),
                    ),
                  ),
                  if (agent.isModerator) ...[
                    const SizedBox(width: 6),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 6,
                        vertical: 2,
                      ),
                      decoration: BoxDecoration(
                        color: Colors.amber.withValues(alpha: 0.2),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: const Text(
                        'moderator',
                        style: TextStyle(fontSize: 10, color: Colors.amber),
                      ),
                    ),
                  ],
                ],
              ),
              const SizedBox(height: 7),
              Row(
                children: [
                  const Icon(
                    Icons.forum_outlined,
                    size: 14,
                    color: Colors.white38,
                  ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      agent.threadTitle?.isNotEmpty == true
                          ? agent.threadTitle!
                          : 'Thread ${agent.threadId}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 12,
                        color: Colors.white54,
                      ),
                    ),
                  ),
                ],
              ),
            ],
          ),
          trailing: IconButton(
            tooltip: 'Open thread',
            onPressed: agent.threadId.isEmpty
                ? null
                : () =>
                      Navigator.pushNamed(context, '/thread/${agent.threadId}'),
            icon: const Icon(Icons.open_in_new_rounded, color: Colors.white38),
          ),
          onTap: () =>
              Navigator.pushNamed(context, '/agent-details/${agent.id}'),
        ),
      ),
    );
  }

  Color _statusColor(String status) {
    switch (status) {
      case 'active':
        return Colors.green;
      case 'draft':
        return Colors.amber;
      case 'paused':
        return Colors.blue;
      case 'archived':
        return Colors.grey;
      default:
        return Colors.white54;
    }
  }
}
