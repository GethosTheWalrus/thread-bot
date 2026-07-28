import 'package:flutter/material.dart';
import 'package:threadbot/models/thread.dart';

class Sidebar extends StatefulWidget {
  final List<ThreadListItem> threads;
  final String? activeThreadId;
  final bool isLoading;
  final Function(String) onThreadTap;
  final VoidCallback onNewChat;
  final Function(String) onDelete;
  final Function(String, String) onRename;
  final Function(String, bool) onPin;
  final VoidCallback onDeleteAll;
  final VoidCallback onMCP;
  final VoidCallback onSkills;
  final VoidCallback onSettings;

  const Sidebar({
    super.key,
    required this.threads,
    this.activeThreadId,
    required this.isLoading,
    required this.onThreadTap,
    required this.onNewChat,
    required this.onDelete,
    required this.onRename,
    required this.onPin,
    required this.onDeleteAll,
    required this.onMCP,
    required this.onSkills,
    required this.onSettings,
  });

  @override
  State<Sidebar> createState() => _SidebarState();
}

class _SidebarState extends State<Sidebar> {
  final TextEditingController _searchController = TextEditingController();
  String _search = '';
  _SidebarSourceFilter _sourceFilter = _SidebarSourceFilter.all;

  List<ThreadListItem> get threads => widget.threads;
  String? get activeThreadId => widget.activeThreadId;
  bool get isLoading => widget.isLoading;
  Function(String) get onThreadTap => widget.onThreadTap;
  VoidCallback get onNewChat => widget.onNewChat;
  Function(String) get onDelete => widget.onDelete;
  Function(String, String) get onRename => widget.onRename;
  Function(String, bool) get onPin => widget.onPin;
  VoidCallback get onDeleteAll => widget.onDeleteAll;
  VoidCallback get onMCP => widget.onMCP;
  VoidCallback get onSkills => widget.onSkills;
  VoidCallback get onSettings => widget.onSettings;

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 280,
      decoration: BoxDecoration(
        color: const Color(0xFF111118),
        border: Border(
          right: BorderSide(color: Colors.white.withValues(alpha: 0.06)),
        ),
      ),
      child: Column(
        children: [
          // New thread button
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 8),
            child: Column(
              children: [
                Material(
                  color: Colors.transparent,
                  child: InkWell(
                    borderRadius: BorderRadius.circular(12),
                    onTap: onNewChat,
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 12,
                      ),
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(12),
                        border: Border.all(
                          color: Colors.white.withValues(alpha: 0.1),
                        ),
                      ),
                      child: Row(
                        children: [
                          Container(
                            width: 28,
                            height: 28,
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(8),
                              gradient: const LinearGradient(
                                colors: [Color(0xFF8B5CF6), Color(0xFF6366F1)],
                              ),
                            ),
                            child: const Icon(
                              Icons.add,
                              size: 16,
                              color: Colors.white,
                            ),
                          ),
                          const SizedBox(width: 10),
                          const Text(
                            'New Thread',
                            style: TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w500,
                              color: Color(0xFFE4E4E7),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 10),
                TextField(
                  controller: _searchController,
                  onChanged: (value) =>
                      setState(() => _search = value.trim().toLowerCase()),
                  style: const TextStyle(
                    fontSize: 13,
                    color: Color(0xFFE4E4E7),
                  ),
                  decoration: InputDecoration(
                    isDense: true,
                    hintText: 'Search threads...',
                    hintStyle: TextStyle(
                      color: Colors.white.withValues(alpha: 0.32),
                    ),
                    prefixIcon: Icon(
                      Icons.search_rounded,
                      size: 18,
                      color: Colors.white.withValues(alpha: 0.35),
                    ),
                    filled: true,
                    fillColor: Colors.white.withValues(alpha: 0.04),
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 10,
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: BorderSide(
                        color: Colors.white.withValues(alpha: 0.07),
                      ),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(12),
                      borderSide: const BorderSide(color: Color(0xFF8B5CF6)),
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: [
                      _buildFilterChip('All', _SidebarSourceFilter.all),
                      _buildFilterChip(
                        'ThreadBot',
                        _SidebarSourceFilter.threadbot,
                      ),
                      _buildFilterChip('Discord', _SidebarSourceFilter.discord),
                      _buildFilterChip('Reachy', _SidebarSourceFilter.reachy),
                      _buildFilterChip('Pinned', _SidebarSourceFilter.pinned),
                    ],
                  ),
                ),
              ],
            ),
          ),

          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Row(
              children: [
                Text(
                  '${_filteredThreads().length} shown',
                  style: TextStyle(
                    fontSize: 11,
                    color: Colors.white.withValues(alpha: 0.35),
                  ),
                ),
                const Spacer(),
                if (_search.isNotEmpty ||
                    _sourceFilter != _SidebarSourceFilter.all)
                  InkWell(
                    borderRadius: BorderRadius.circular(999),
                    onTap: () => setState(() {
                      _searchController.clear();
                      _search = '';
                      _sourceFilter = _SidebarSourceFilter.all;
                    }),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 8,
                        vertical: 4,
                      ),
                      child: Text(
                        'Reset',
                        style: TextStyle(
                          fontSize: 11,
                          color: Colors.white.withValues(alpha: 0.45),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 4),

          // Thread list
          Expanded(
            child: isLoading && threads.isEmpty
                ? const Center(
                    child: SizedBox(
                      width: 24,
                      height: 24,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        valueColor: AlwaysStoppedAnimation(Color(0xFF8B5CF6)),
                      ),
                    ),
                  )
                : threads.isEmpty
                ? Center(
                    child: Text(
                      'No conversations yet',
                      style: TextStyle(
                        fontSize: 13,
                        color: Colors.white.withValues(alpha: 0.3),
                      ),
                    ),
                  )
                : _buildGroupedThreadList(context),
          ),

          // Bottom actions
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              border: Border(
                top: BorderSide(color: Colors.white.withValues(alpha: 0.06)),
              ),
            ),
            child: Material(
              color: Colors.transparent,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  InkWell(
                    borderRadius: BorderRadius.circular(10),
                    onTap: onSkills,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 10,
                      ),
                      child: Row(
                        children: [
                          Container(
                            width: 18,
                            height: 18,
                            alignment: Alignment.center,
                            decoration: BoxDecoration(
                              color: const Color(
                                0xFF8B5CF6,
                              ).withValues(alpha: 0.18),
                              borderRadius: BorderRadius.circular(5),
                              border: Border.all(
                                color: const Color(
                                  0xFF8B5CF6,
                                ).withValues(alpha: 0.55),
                              ),
                            ),
                            child: const Text(
                              'S',
                              style: TextStyle(
                                fontSize: 11,
                                fontWeight: FontWeight.w700,
                                color: Color(0xFFC4B5FD),
                              ),
                            ),
                          ),
                          const SizedBox(width: 10),
                          const Text(
                            'Skills',
                            style: TextStyle(
                              fontSize: 13,
                              color: Color(0xFFE4E4E7),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 4),
                  InkWell(
                    borderRadius: BorderRadius.circular(10),
                    onTap: onMCP,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 10,
                      ),
                      child: Row(
                        children: [
                          Icon(
                            Icons.terminal_rounded,
                            size: 18,
                            color: const Color(
                              0xFF8B5CF6,
                            ).withValues(alpha: 0.7),
                          ),
                          const SizedBox(width: 10),
                          const Text(
                            'MCP Servers',
                            style: TextStyle(
                              fontSize: 13,
                              color: Color(0xFFE4E4E7),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 4),
                  InkWell(
                    borderRadius: BorderRadius.circular(10),
                    onTap: onSettings,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 12,
                        vertical: 10,
                      ),
                      child: Row(
                        children: [
                          Icon(
                            Icons.tune_rounded,
                            size: 18,
                            color: Colors.white.withValues(alpha: 0.5),
                          ),
                          const SizedBox(width: 10),
                          Text(
                            'Settings',
                            style: TextStyle(
                              fontSize: 13,
                              color: Colors.white.withValues(alpha: 0.5),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  if (threads.isNotEmpty) ...[
                    const SizedBox(height: 10),
                    Divider(
                      color: Colors.white.withValues(alpha: 0.06),
                      height: 1,
                    ),
                    const SizedBox(height: 6),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton.icon(
                        style: TextButton.styleFrom(
                          foregroundColor: Colors.red.shade400.withValues(
                            alpha: 0.72,
                          ),
                          padding: const EdgeInsets.symmetric(
                            horizontal: 10,
                            vertical: 8,
                          ),
                          minimumSize: Size.zero,
                          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        ),
                        onPressed: () => _showClearAllDialog(context),
                        icon: const Icon(Icons.delete_sweep_outlined, size: 15),
                        label: const Text(
                          'Clear all',
                          style: TextStyle(fontSize: 12),
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildGroupedThreadList(BuildContext context) {
    final visibleThreads = _filteredThreads();
    if (visibleThreads.isEmpty) {
      final message = _search.isNotEmpty
          ? 'No threads match "${_searchController.text.trim()}"'
          : 'No threads in this filter';
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(
            message,
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: 13,
              color: Colors.white.withValues(alpha: 0.35),
            ),
          ),
        ),
      );
    }

    final pinnedThreads = visibleThreads
        .where((thread) => thread.isPinned)
        .toList();
    final regularThreads = _sourceFilter == _SidebarSourceFilter.pinned
        ? <ThreadListItem>[]
        : visibleThreads.where((thread) => !thread.isPinned).toList();
    final dateGroups = _groupThreadsByDate(regularThreads);

    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      children: [
        if (pinnedThreads.isNotEmpty)
          _buildSidebarSection(
            context,
            title: 'Pinned',
            icon: Icons.push_pin_rounded,
            threads: pinnedThreads,
            accent: const Color(0xFFFBBF24),
          ),
        for (final group in dateGroups)
          _buildSidebarSection(
            context,
            title: group.name,
            icon: Icons.history_rounded,
            threads: group.threads,
          ),
        const SizedBox(height: 8),
      ],
    );
  }

  Widget _buildFilterChip(String label, _SidebarSourceFilter filter) {
    final selected = _sourceFilter == filter;
    return Padding(
      padding: const EdgeInsets.only(right: 6),
      child: InkWell(
        borderRadius: BorderRadius.circular(999),
        onTap: () => setState(() => _sourceFilter = filter),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(999),
            color: selected
                ? const Color(0xFF8B5CF6).withValues(alpha: 0.18)
                : Colors.white.withValues(alpha: 0.04),
            border: Border.all(
              color: selected
                  ? const Color(0xFF8B5CF6).withValues(alpha: 0.45)
                  : Colors.white.withValues(alpha: 0.06),
            ),
          ),
          child: Text(
            label,
            style: TextStyle(
              fontSize: 11,
              fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
              color: selected
                  ? const Color(0xFFC4B5FD)
                  : Colors.white.withValues(alpha: 0.55),
            ),
          ),
        ),
      ),
    );
  }

  List<ThreadListItem> _filteredThreads() {
    final filtered = threads.where((thread) {
      final matchesSource = switch (_sourceFilter) {
        _SidebarSourceFilter.all => true,
        _SidebarSourceFilter.threadbot =>
          !thread.isDiscordThread && !thread.isReachyThread,
        _SidebarSourceFilter.discord => thread.isDiscordThread,
        _SidebarSourceFilter.reachy => thread.isReachyThread,
        _SidebarSourceFilter.pinned => thread.isPinned,
      };
      if (!matchesSource) return false;
      if (_search.isEmpty) return true;

      final haystack = [
        thread.title,
        thread.discordServerName ?? '',
        _sourceLabel(thread),
        '${thread.messageCount}',
      ].join(' ').toLowerCase();
      return haystack.contains(_search);
    }).toList();

    filtered.sort((a, b) {
      if (a.isPinned != b.isPinned) return a.isPinned ? -1 : 1;
      return b.updatedAt.compareTo(a.updatedAt);
    });
    return filtered;
  }

  List<_SidebarThreadGroup> _groupThreadsByDate(List<ThreadListItem> items) {
    final grouped = <String, List<ThreadListItem>>{};
    for (final thread in items) {
      final groupName = _dateGroupName(thread.updatedAt);
      grouped.putIfAbsent(groupName, () => <ThreadListItem>[]).add(thread);
    }

    final order = [
      'Today',
      'Yesterday',
      'Previous 7 days',
      'Previous 30 days',
      'Older',
    ];
    final entries = grouped.entries.toList()
      ..sort((a, b) => order.indexOf(a.key).compareTo(order.indexOf(b.key)));

    for (final entry in entries) {
      entry.value.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    }

    return entries
        .map(
          (entry) => _SidebarThreadGroup(name: entry.key, threads: entry.value),
        )
        .toList();
  }

  Widget _buildSidebarSection(
    BuildContext context, {
    required String title,
    required IconData icon,
    required List<ThreadListItem> threads,
    Color? accent,
  }) {
    final color = accent ?? Colors.white.withValues(alpha: 0.42);
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(10, 8, 10, 6),
            child: Row(
              children: [
                Icon(icon, size: 14, color: color),
                const SizedBox(width: 7),
                Expanded(
                  child: Text(
                    title,
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w800,
                      letterSpacing: 0.35,
                      color: Colors.white.withValues(alpha: 0.46),
                    ),
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 7,
                    vertical: 2,
                  ),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(999),
                    color: Colors.white.withValues(alpha: 0.055),
                  ),
                  child: Text(
                    '${threads.length}',
                    style: TextStyle(
                      fontSize: 10,
                      color: Colors.white.withValues(alpha: 0.45),
                    ),
                  ),
                ),
              ],
            ),
          ),
          for (final thread in threads) _buildThreadTile(context, thread),
        ],
      ),
    );
  }

  String _dateGroupName(DateTime date) {
    final now = DateTime.now();
    final local = date.toLocal();
    final today = DateTime(now.year, now.month, now.day);
    final day = DateTime(local.year, local.month, local.day);
    final age = today.difference(day).inDays;
    if (age <= 0) return 'Today';
    if (age == 1) return 'Yesterday';
    if (age <= 7) return 'Previous 7 days';
    if (age <= 30) return 'Previous 30 days';
    return 'Older';
  }

  String _sourceLabel(ThreadListItem thread) {
    if (thread.isReachyThread) return 'Reachy';
    if (thread.isDiscordThread) {
      final serverName = thread.discordServerName?.trim();
      return serverName?.isNotEmpty == true ? serverName! : 'Discord';
    }
    return 'ThreadBot';
  }

  Color _sourceColor(ThreadListItem thread, bool isActive) {
    if (thread.isReachyThread) return const Color(0xFF34D399);
    if (thread.isDiscordThread) return const Color(0xFF5865F2);
    return isActive
        ? const Color(0xFF8B5CF6)
        : Colors.white.withValues(alpha: 0.38);
  }

  Widget _sourceBadge(ThreadListItem thread, bool isActive) {
    final color = _sourceColor(thread, isActive);
    final icon = thread.isReachyThread
        ? Icons.smart_toy_outlined
        : thread.isDiscordThread
        ? Icons.discord
        : Icons.chat_bubble_outline;
    return Container(
      width: 22,
      height: 22,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(7),
        color: color.withValues(alpha: isActive ? 0.18 : 0.1),
        border: Border.all(
          color: color.withValues(alpha: isActive ? 0.45 : 0.18),
        ),
      ),
      child: Icon(icon, size: 13, color: color),
    );
  }

  String _relativeTime(DateTime date) {
    final diff = DateTime.now().difference(date.toLocal());
    if (diff.inMinutes < 1) return 'now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m';
    if (diff.inHours < 24) return '${diff.inHours}h';
    if (diff.inDays < 7) return '${diff.inDays}d';
    return '${date.toLocal().month}/${date.toLocal().day}';
  }

  Widget _buildThreadMeta(ThreadListItem thread, bool isActive) {
    final source = _sourceLabel(thread);
    return Row(
      children: [
        Flexible(
          child: Text(
            source,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(
              fontSize: 11,
              color: isActive
                  ? const Color(0xFFC4B5FD)
                  : Colors.white.withValues(alpha: 0.34),
            ),
          ),
        ),
        Text(
          '  |  ${_relativeTime(thread.updatedAt)}  |  ${thread.messageCount} msg',
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            fontSize: 11,
            color: Colors.white.withValues(alpha: 0.3),
          ),
        ),
      ],
    );
  }

  Widget _buildPinButton(ThreadListItem thread) {
    return InkWell(
      borderRadius: BorderRadius.circular(999),
      onTap: () => onPin(thread.id, !thread.isPinned),
      child: Padding(
        padding: const EdgeInsets.all(5),
        child: Icon(
          thread.isPinned ? Icons.push_pin_rounded : Icons.push_pin_outlined,
          size: 15,
          color: thread.isPinned
              ? const Color(0xFFFBBF24)
              : Colors.white.withValues(alpha: 0.28),
        ),
      ),
    );
  }

  Widget _buildThreadTile(BuildContext context, ThreadListItem thread) {
    final isActive = thread.id == activeThreadId;
    final isGeneratingTitle = thread.title == 'New Thread';

    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Material(
        color: Colors.transparent,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () => onThreadTap(thread.id),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            padding: const EdgeInsets.fromLTRB(10, 9, 6, 9),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              color: isActive
                  ? const Color(0xFF8B5CF6).withValues(alpha: 0.12)
                  : Colors.transparent,
              border: Border.all(
                color: isActive
                    ? const Color(0xFF8B5CF6).withValues(alpha: 0.28)
                    : Colors.white.withValues(alpha: 0.0),
              ),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                isGeneratingTitle
                    ? const SizedBox(
                        width: 22,
                        height: 22,
                        child: Padding(
                          padding: EdgeInsets.all(4),
                          child: CircularProgressIndicator(
                            strokeWidth: 1.7,
                            valueColor: AlwaysStoppedAnimation(
                              Color(0xFF8B5CF6),
                            ),
                          ),
                        ),
                      )
                    : _sourceBadge(thread, isActive),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              isGeneratingTitle
                                  ? 'Generating title...'
                                  : thread.title,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                fontSize: 13,
                                fontWeight: isActive
                                    ? FontWeight.w700
                                    : FontWeight.w500,
                                color: isActive
                                    ? const Color(0xFFEDE9FE)
                                    : Colors.white.withValues(alpha: 0.72),
                                fontStyle: isGeneratingTitle
                                    ? FontStyle.italic
                                    : FontStyle.normal,
                              ),
                            ),
                          ),
                          if (thread.isPinned)
                            const Padding(
                              padding: EdgeInsets.only(left: 4),
                              child: Icon(
                                Icons.push_pin_rounded,
                                size: 12,
                                color: Color(0xFFFBBF24),
                              ),
                            ),
                        ],
                      ),
                      const SizedBox(height: 3),
                      _buildThreadMeta(thread, isActive),
                    ],
                  ),
                ),
                _buildPinButton(thread),
                PopupMenuButton<String>(
                  icon: Icon(
                    Icons.more_horiz,
                    size: 16,
                    color: Colors.white.withValues(alpha: 0.38),
                  ),
                  padding: EdgeInsets.zero,
                  constraints: const BoxConstraints(),
                  position: PopupMenuPosition.under,
                  color: const Color(0xFF1C1C26),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                    side: BorderSide(
                      color: Colors.white.withValues(alpha: 0.08),
                    ),
                  ),
                  onSelected: (value) {
                    if (value == 'pin') {
                      onPin(thread.id, !thread.isPinned);
                    } else if (value == 'rename') {
                      _showRenameDialog(context, thread);
                    } else if (value == 'delete') {
                      _showDeleteDialog(context, thread);
                    }
                  },
                  itemBuilder: (_) => [
                    PopupMenuItem(
                      value: 'pin',
                      height: 40,
                      child: Row(
                        children: [
                          Icon(
                            thread.isPinned
                                ? Icons.push_pin_outlined
                                : Icons.push_pin_rounded,
                            size: 16,
                            color: const Color(0xFFFBBF24),
                          ),
                          const SizedBox(width: 8),
                          Text(
                            thread.isPinned ? 'Unpin' : 'Pin',
                            style: const TextStyle(fontSize: 13),
                          ),
                        ],
                      ),
                    ),
                    PopupMenuItem(
                      value: 'rename',
                      height: 40,
                      child: Row(
                        children: [
                          Icon(
                            Icons.edit_outlined,
                            size: 16,
                            color: Colors.white.withValues(alpha: 0.7),
                          ),
                          const SizedBox(width: 8),
                          const Text('Rename', style: TextStyle(fontSize: 13)),
                        ],
                      ),
                    ),
                    PopupMenuItem(
                      value: 'delete',
                      height: 40,
                      child: Row(
                        children: [
                          Icon(
                            Icons.delete_outline,
                            size: 16,
                            color: Colors.red.shade400,
                          ),
                          const SizedBox(width: 8),
                          Text(
                            'Delete',
                            style: TextStyle(
                              fontSize: 13,
                              color: Colors.red.shade400,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  void _showRenameDialog(BuildContext context, ThreadListItem thread) {
    final controller = TextEditingController(text: thread.title);
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1C1C26),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Rename thread'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(hintText: 'Thread title'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              if (controller.text.trim().isNotEmpty) {
                onRename(thread.id, controller.text.trim());
              }
              Navigator.pop(ctx);
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
  }

  void _showDeleteDialog(BuildContext context, ThreadListItem thread) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1C1C26),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Delete thread?'),
        content: const Text('This action cannot be undone.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Colors.red.shade700),
            onPressed: () {
              onDelete(thread.id);
              Navigator.pop(ctx);
            },
            child: const Text('Delete'),
          ),
        ],
      ),
    );
  }

  void _showClearAllDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1C1C26),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        title: const Text('Clear all conversations?'),
        content: const Text(
          'This will permanently delete all threads and messages.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Colors.red.shade700),
            onPressed: () {
              onDeleteAll();
              Navigator.pop(ctx);
            },
            child: const Text('Delete All'),
          ),
        ],
      ),
    );
  }
}

class _SidebarThreadGroup {
  final String name;
  final List<ThreadListItem> threads;

  const _SidebarThreadGroup({required this.name, required this.threads});
}

enum _SidebarSourceFilter { all, threadbot, discord, reachy, pinned }
