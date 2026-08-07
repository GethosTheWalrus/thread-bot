import 'dart:async';
import 'package:flutter/material.dart';
import 'package:threadbot/models/autonomy.dart';
import 'package:threadbot/services/autonomy_api.dart';
import 'package:threadbot/widgets/agent_workspace_ui.dart';

class AgentListScreen extends StatefulWidget {
  final AutonomyApiService api;
  const AgentListScreen({super.key, required this.api});
  @override
  State<AgentListScreen> createState() => _AgentListScreenState();
}

class _AgentListScreenState extends State<AgentListScreen> {
  List<Agent> _agents = [];
  bool _loading = true, _loadingMore = false;
  String? _error, _nextCursor;
  final _search = TextEditingController();
  Timer? _debounce;
  String _status = 'all';
  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  void _changed(String _) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), _load);
    setState(() {});
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final page = await widget.api.agents(
        limit: 50,
        query: _search.text,
        status: _status,
      );
      if (mounted)
        setState(() {
          _agents = page.items;
          _nextCursor = page.nextCursor;
        });
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _more() async {
    if (_nextCursor == null || _loadingMore) return;
    setState(() => _loadingMore = true);
    try {
      final page = await widget.api.agents(
        cursor: _nextCursor,
        limit: 50,
        query: _search.text,
        status: _status,
      );
      if (mounted)
        setState(() {
          final ids = _agents.map((a) => a.id).toSet();
          _agents.addAll(page.items.where((a) => ids.add(a.id)));
          _nextCursor = page.nextCursor;
        });
    } catch (e) {
      if (mounted)
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not load more agents: $e')),
        );
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 1180),
          child: _loading && _agents.isEmpty
              ? const AgentStateView(
                  icon: Icons.hourglass_top_rounded,
                  title: 'Loading agents',
                  message: 'Fetching your agent workspace…',
                )
              : _error != null
              ? AgentStateView(
                  icon: Icons.cloud_off_rounded,
                  title: 'Could not load agents',
                  message: _error!,
                  onAction: _load,
                )
              : _content(),
        ),
      ),
    ),
  );
  Widget _content() => LayoutBuilder(
    builder: (_, constraints) => ListView(
      padding: const EdgeInsets.fromLTRB(24, 28, 24, 48),
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () {
              if (Navigator.canPop(context)) {
                Navigator.pop(context);
              } else {
                Navigator.pushReplacementNamed(context, '/');
              }
            },
            icon: const Icon(Icons.arrow_back_rounded, size: 18),
            label: const Text('Back to Threads'),
          ),
        ),
        const SizedBox(height: 8),
        AgentPageHeader(
          eyebrow: 'Workspace',
          title: 'Agents',
          description:
              'Build focused operators that belong to a Thread and can work on its behalf.',
          action: Wrap(
            spacing: 8,
            children: [
              IconButton(
                tooltip: 'Refresh agents',
                onPressed: _load,
                icon: const Icon(Icons.refresh_rounded),
              ),
              FilledButton.icon(
                onPressed: () => Navigator.pushNamed(context, '/agents/new'),
                icon: const Icon(Icons.add, size: 18),
                label: const Text('New agent'),
              ),
            ],
          ),
        ),
        if (_loading) ...[
          const LinearProgressIndicator(minHeight: 2),
          const SizedBox(height: 16),
        ],
        _filters(constraints.maxWidth),
        const SizedBox(height: 18),
        _summary(),
        const SizedBox(height: 14),
        if (_agents.isEmpty)
          AgentStateView(
            icon: Icons.manage_search_rounded,
            title: 'No matching agents',
            message: 'Try another search or clear the filters.',
            onAction: () {
              _search.clear();
              setState(() => _status = 'all');
              _load();
            },
            actionLabel: 'Clear filters',
          )
        else ...[
          LayoutBuilder(
            builder: (_, grid) => GridView.builder(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              gridDelegate: SliverGridDelegateWithMaxCrossAxisExtent(
                maxCrossAxisExtent: 420,
                mainAxisExtent: 214,
                crossAxisSpacing: 12,
                mainAxisSpacing: 12,
              ),
              itemCount: _agents.length,
              itemBuilder: (_, i) => _card(_agents[i]),
            ),
          ),
          if (_nextCursor != null)
            Padding(
              padding: const EdgeInsets.only(top: 20),
              child: Center(
                child: OutlinedButton.icon(
                  onPressed: _loadingMore ? null : _more,
                  icon: _loadingMore
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.expand_more),
                  label: Text(_loadingMore ? 'Loading…' : 'Load more'),
                ),
              ),
            ),
        ],
      ],
    ),
  );
  Widget _filters(double width) => Wrap(
    spacing: 10,
    runSpacing: 10,
    crossAxisAlignment: WrapCrossAlignment.center,
    children: [
      SizedBox(
        width: width > 600 ? 360 : width,
        child: TextField(
          controller: _search,
          onChanged: _changed,
          decoration: InputDecoration(
            hintText: 'Search agents or Threads',
            prefixIcon: const Icon(Icons.search_rounded),
            suffixIcon: _search.text.isEmpty
                ? null
                : IconButton(
                    tooltip: 'Clear search',
                    onPressed: () {
                      _search.clear();
                      _load();
                      setState(() {});
                    },
                    icon: const Icon(Icons.close),
                  ),
            filled: true,
          ),
        ),
      ),
      _chips(
        'Status',
        _status,
        {
          'all': 'All',
          'active': 'Active',
          'draft': 'Draft',
          'paused': 'Paused',
          'archived': 'Archived',
        },
        (v) {
          setState(() => _status = v);
          _load();
        },
      ),
    ],
  );
  Widget _chips(
    String label,
    String value,
    Map<String, String> values,
    ValueChanged<String> changed,
  ) => PopupMenuButton<String>(
    tooltip: label,
    onSelected: changed,
    itemBuilder: (_) => values.entries
        .map((e) => PopupMenuItem(value: e.key, child: Text(e.value)))
        .toList(),
    child: Chip(
      avatar: const Icon(Icons.tune_rounded, size: 16),
      label: Text('$label: ${values[value]}'),
    ),
  );
  Widget _summary() {
    final active = _agents.where((a) => a.status == 'active').length;
    final drafts = _agents.where((a) => a.status == 'draft').length;
    return Wrap(
      spacing: 10,
      runSpacing: 10,
      children: [
        AgentMetric(
          label: 'Visible agents',
          value: '${_agents.length}',
          icon: Icons.groups_rounded,
        ),
        AgentMetric(
          label: 'Active',
          value: '$active',
          icon: Icons.play_circle_outline,
        ),
        AgentMetric(
          label: 'Drafts',
          value: '$drafts',
          icon: Icons.edit_note_rounded,
        ),
      ],
    );
  }

  Widget _card(Agent a) => Semantics(
    button: true,
    label: 'Open ${a.name}',
    child: InkWell(
      borderRadius: BorderRadius.circular(14),
      onTap: () => Navigator.pushNamed(context, '/agent-details/${a.id}'),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: agentSurface,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: agentBorder),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: AgentIdentity(
                    name: a.name,
                    handle: a.handle,
                    radius: 19,
                  ),
                ),
                AgentStatusPill(a.status),
              ],
            ),
            if (a.description?.trim().isNotEmpty == true) ...[
              const SizedBox(height: 12),
              Text(
                a.description!.trim(),
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: Colors.white54,
                  fontSize: 12,
                  height: 1.35,
                ),
              ),
            ],
            const Spacer(),
            Row(
              children: [
                const Icon(
                  Icons.forum_outlined,
                  size: 15,
                  color: Colors.white38,
                ),
                const SizedBox(width: 7),
                Expanded(
                  child: Text(
                    a.threadTitle?.isNotEmpty == true
                        ? a.threadTitle!
                        : 'Thread ${a.threadId}',
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: Colors.white60, fontSize: 12),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                const Text(
                  'Participant Agent',
                  style: TextStyle(color: Colors.white38, fontSize: 11),
                ),
                const Spacer(),
                TextButton(
                  onPressed: a.threadId.isEmpty
                      ? null
                      : () => Navigator.pushNamed(
                          context,
                          '/thread/${a.threadId}',
                        ),
                  child: const Text('Open Thread'),
                ),
                const Icon(
                  Icons.chevron_right_rounded,
                  size: 18,
                  color: Colors.white38,
                ),
              ],
            ),
          ],
        ),
      ),
    ),
  );
}
