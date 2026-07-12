import 'package:flutter/material.dart';
import 'package:threadbot/models/thread.dart';

class Sidebar extends StatelessWidget {
  final List<ThreadListItem> threads;
  final String? activeThreadId;
  final bool isLoading;
  final Function(String) onThreadTap;
  final VoidCallback onNewChat;
  final Function(String) onDelete;
  final Function(String, String) onRename;
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
    required this.onDeleteAll,
    required this.onMCP,
    required this.onSkills,
    required this.onSettings,
  });

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
            padding: const EdgeInsets.all(12),
            child: Material(
              color: Colors.transparent,
              child: InkWell(
                borderRadius: BorderRadius.circular(12),
                onTap: onNewChat,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: Colors.white.withValues(alpha: 0.1)),
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
                        child: const Icon(Icons.add, size: 16, color: Colors.white),
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
          ),

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
                  if (threads.isNotEmpty)
                    InkWell(
                      borderRadius: BorderRadius.circular(10),
                      onTap: () => _showClearAllDialog(context),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                        child: Row(
                          children: [
                            Icon(Icons.delete_sweep_outlined, size: 18, color: Colors.red.shade400.withValues(alpha: 0.7)),
                            const SizedBox(width: 10),
                            Text(
                              'Clear conversations',
                              style: TextStyle(
                                fontSize: 13,
                                color: Colors.red.shade400.withValues(alpha: 0.7),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  const SizedBox(height: 4),
                  InkWell(
                    borderRadius: BorderRadius.circular(10),
                    onTap: onSkills,
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                      child: Row(
                        children: [
                          Icon(Icons.extension_rounded, size: 18, color: const Color(0xFF8B5CF6).withValues(alpha: 0.7)),
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
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                      child: Row(
                        children: [
                          Icon(Icons.terminal_rounded, size: 18, color: const Color(0xFF8B5CF6).withValues(alpha: 0.7)),
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
                      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                      child: Row(
                        children: [
                          Icon(Icons.tune_rounded, size: 18, color: Colors.white.withValues(alpha: 0.5)),
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
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildGroupedThreadList(BuildContext context) {
    final grouped = _groupThreadsBySidebarCategory();

    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 8),
      children: [
        for (final group in grouped) ...[
          _buildSidebarGroup(context, group),
        ],
        const SizedBox(height: 8),
      ],
    );
  }

  List<_SidebarThreadGroup> _groupThreadsBySidebarCategory() {
    final grouped = <String, List<ThreadListItem>>{};
    for (final thread in threads) {
      final groupName = thread.isDiscordThread
          ? (thread.discordServerName?.trim().isNotEmpty == true
              ? thread.discordServerName!.trim()
              : 'Discord')
          : 'ThreadBot';
      grouped.putIfAbsent(groupName, () => <ThreadListItem>[]).add(thread);
    }

    final entries = grouped.entries.toList()
      ..sort((a, b) {
        if (a.key == 'ThreadBot') return -1;
        if (b.key == 'ThreadBot') return 1;
        return a.key.toLowerCase().compareTo(b.key.toLowerCase());
      });

    for (final entry in entries) {
      entry.value.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    }

    return entries
        .map((entry) => _SidebarThreadGroup(name: entry.key, threads: entry.value))
        .toList();
  }

  Widget _buildSidebarGroup(BuildContext context, _SidebarThreadGroup group) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          key: PageStorageKey<String>('sidebar-group-${group.name}'),
          initiallyExpanded: true,
          tilePadding: const EdgeInsets.symmetric(horizontal: 12),
          childrenPadding: const EdgeInsets.only(left: 8, right: 8, bottom: 4),
          iconColor: const Color(0xFF8B5CF6),
          collapsedIconColor: Colors.white.withValues(alpha: 0.35),
          title: Row(
            children: [
              Icon(
                group.name == 'ThreadBot' ? Icons.chat_bubble_outline : Icons.discord,
                size: 16,
                color: group.name == 'ThreadBot'
                    ? Colors.white.withValues(alpha: 0.45)
                    : const Color(0xFF8B5CF6),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  group.name,
                  style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              const SizedBox(width: 8),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(999),
                  color: Colors.white.withValues(alpha: 0.06),
                ),
                child: Text(
                  '${group.threads.length}',
                  style: TextStyle(fontSize: 11, color: Colors.white.withValues(alpha: 0.6)),
                ),
              ),
            ],
          ),
          children: group.threads.map((t) => _buildThreadTile(context, t)).toList(),
        ),
      ),
    );
  }

  Widget _buildThreadTile(BuildContext context, ThreadListItem thread) {
    final isActive = thread.id == activeThreadId;

    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: Material(
        color: Colors.transparent,
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          borderRadius: BorderRadius.circular(10),
          onTap: () => onThreadTap(thread.id),
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(10),
              color: isActive
                  ? Colors.white.withValues(alpha: 0.08)
                  : Colors.transparent,
            ),
            child: Row(
              children: [
                SizedBox(
                  width: 14,
                  height: 14,
                    child: thread.title == 'New Thread'
                        ? const CircularProgressIndicator(
                          strokeWidth: 1.5,
                          valueColor: AlwaysStoppedAnimation(Color(0xFF8B5CF6)),
                        )
                        : thread.isDiscordThread
                            ? _DiscordGlyph(isActive: isActive)
                            : Icon(
                                Icons.chat_bubble_outline,
                                size: 14,
                                color: isActive
                                    ? const Color(0xFF8B5CF6)
                                    : Colors.white.withValues(alpha: 0.3),
                              ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    thread.title == 'New Thread' ? 'Generating title...' : thread.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: isActive ? FontWeight.w500 : FontWeight.w400,
                      color: isActive
                          ? const Color(0xFFE4E4E7)
                          : Colors.white.withValues(alpha: 0.6),
                      fontStyle: thread.title == 'New Thread' ? FontStyle.italic : FontStyle.normal,
                    ),
                  ),
                ),
                PopupMenuButton<String>(
                    icon: Icon(
                      Icons.more_horiz,
                      size: 16,
                      color: Colors.white.withValues(alpha: 0.4),
                    ),
                    padding: EdgeInsets.zero,
                    constraints: const BoxConstraints(),
                    position: PopupMenuPosition.under,
                    color: const Color(0xFF1C1C26),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(12),
                      side: BorderSide(color: Colors.white.withValues(alpha: 0.08)),
                    ),
                    onSelected: (value) {
                      if (value == 'rename') {
                        _showRenameDialog(context, thread);
                      } else if (value == 'delete') {
                        _showDeleteDialog(context, thread);
                      }
                    },
                    itemBuilder: (_) => [
                      PopupMenuItem(
                        value: 'rename',
                        height: 40,
                        child: Row(
                          children: [
                            Icon(Icons.edit_outlined, size: 16, color: Colors.white.withValues(alpha: 0.7)),
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
                            Icon(Icons.delete_outline, size: 16, color: Colors.red.shade400),
                            const SizedBox(width: 8),
                            Text('Delete', style: TextStyle(fontSize: 13, color: Colors.red.shade400)),
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
        content: const Text('This will permanently delete all threads and messages.'),
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

class _DiscordGlyph extends StatelessWidget {
  final bool isActive;

  const _DiscordGlyph({required this.isActive});

  @override
  Widget build(BuildContext context) {
    return Icon(
      Icons.discord,
      size: 14,
      color: isActive ? const Color(0xFF5865F2) : Colors.white.withValues(alpha: 0.25),
    );
  }
}
