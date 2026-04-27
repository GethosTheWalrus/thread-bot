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
          // New chat button
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
                        'New Chat',
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
              child: InkWell(
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
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildGroupedThreadList(BuildContext context) {
    // Group threads: Today, Yesterday, Previous 7 Days, Older
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final yesterday = today.subtract(const Duration(days: 1));
    final weekAgo = today.subtract(const Duration(days: 7));

    final todayThreads = <ThreadListItem>[];
    final yesterdayThreads = <ThreadListItem>[];
    final weekThreads = <ThreadListItem>[];
    final olderThreads = <ThreadListItem>[];

    for (final t in threads) {
      final date = DateTime(t.updatedAt.year, t.updatedAt.month, t.updatedAt.day);
      if (!date.isBefore(today)) {
        todayThreads.add(t);
      } else if (!date.isBefore(yesterday)) {
        yesterdayThreads.add(t);
      } else if (!date.isBefore(weekAgo)) {
        weekThreads.add(t);
      } else {
        olderThreads.add(t);
      }
    }

    return ListView(
      padding: const EdgeInsets.symmetric(horizontal: 8),
      children: [
        if (todayThreads.isNotEmpty) ...[
          _buildGroupHeader('Today'),
          ...todayThreads.map((t) => _buildThreadTile(context, t)),
        ],
        if (yesterdayThreads.isNotEmpty) ...[
          _buildGroupHeader('Yesterday'),
          ...yesterdayThreads.map((t) => _buildThreadTile(context, t)),
        ],
        if (weekThreads.isNotEmpty) ...[
          _buildGroupHeader('Previous 7 days'),
          ...weekThreads.map((t) => _buildThreadTile(context, t)),
        ],
        if (olderThreads.isNotEmpty) ...[
          _buildGroupHeader('Older'),
          ...olderThreads.map((t) => _buildThreadTile(context, t)),
        ],
        const SizedBox(height: 8),
      ],
    );
  }

  Widget _buildGroupHeader(String label) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 16, 12, 6),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 11,
          fontWeight: FontWeight.w600,
          color: Colors.white.withValues(alpha: 0.3),
          letterSpacing: 0.5,
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
                Icon(
                  Icons.chat_bubble_outline,
                  size: 14,
                  color: isActive
                      ? const Color(0xFF8B5CF6)
                      : Colors.white.withValues(alpha: 0.3),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    thread.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: isActive ? FontWeight.w500 : FontWeight.w400,
                      color: isActive
                          ? const Color(0xFFE4E4E7)
                          : Colors.white.withValues(alpha: 0.6),
                    ),
                  ),
                ),
                if (isActive)
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
}
