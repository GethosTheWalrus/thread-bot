import 'package:flutter/material.dart';
import 'package:threadbot/models/message.dart';
import 'package:threadbot/models/thread.dart';
import 'package:threadbot/services/api_service.dart';
import 'package:threadbot/widgets/chat_message_list.dart';
import 'package:threadbot/widgets/chat_input.dart';
import 'package:threadbot/widgets/sidebar.dart';
import 'package:threadbot/screens/settings_screen.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> with TickerProviderStateMixin {
  final ApiService _api = ApiService();
  final ScrollController _scrollController = ScrollController();

  // State
  List<ThreadListItem> _threads = [];
  String? _activeThreadId;
  List<Message> _messages = [];
  bool _isLoadingThreads = false;
  bool _isLoadingMessages = false;
  bool _isSending = false;
  String? _error;
  bool _sidebarOpen = true;

  // Animation
  late final AnimationController _fadeController;
  late final Animation<double> _fadeAnimation;

  @override
  void initState() {
    super.initState();
    _fadeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 400),
    );
    _fadeAnimation = CurvedAnimation(
      parent: _fadeController,
      curve: Curves.easeOut,
    );
    _fadeController.forward();
    _loadThreads();
  }

  @override
  void dispose() {
    _fadeController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  // ── Data Loading ──────────────────────────────────────────────────

  Future<void> _loadThreads() async {
    setState(() => _isLoadingThreads = true);
    try {
      final threads = await _api.getThreads();
      if (mounted) setState(() { _threads = threads; _isLoadingThreads = false; });
    } catch (e) {
      if (mounted) setState(() { _error = 'Failed to load threads'; _isLoadingThreads = false; });
    }
  }

  Future<void> _loadThread(String threadId) async {
    setState(() { _isLoadingMessages = true; _activeThreadId = threadId; _error = null; });
    try {
      final thread = await _api.getThread(threadId);
      if (mounted) {
        setState(() { _messages = thread.messages; _isLoadingMessages = false; });
        _scrollToBottom();
      }
    } catch (e) {
      if (mounted) setState(() { _error = 'Failed to load thread'; _isLoadingMessages = false; });
    }
  }

  Future<void> _sendMessage(String content) async {
    if (_isSending) return;

    setState(() => _isSending = true);

    // Optimistic UI: add user message immediately
    final optimisticMsg = Message(
      id: 'temp-${DateTime.now().millisecondsSinceEpoch}',
      threadId: _activeThreadId ?? '',
      role: 'user',
      content: content,
      createdAt: DateTime.now(),
    );
    setState(() => _messages.add(optimisticMsg));
    _scrollToBottom();

    try {
      final thread = await _api.sendMessage(content, threadId: _activeThreadId);

      if (mounted) {
        setState(() {
          _activeThreadId = thread.id;
          _messages = thread.messages;
          _isSending = false;
        });
        _scrollToBottom();
        _loadThreads(); // refresh sidebar
      }
    } catch (e) {
      if (mounted) {
        // Remove optimistic message on error
        setState(() {
          _messages.removeWhere((m) => m.id == optimisticMsg.id);
          _isSending = false;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Error: $e'),
            backgroundColor: Colors.red.shade800,
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
          ),
        );
      }
    }
  }

  Future<void> _startNewChat() async {
    setState(() {
      _activeThreadId = null;
      _messages = [];
      _error = null;
    });
  }

  Future<void> _deleteThread(String threadId) async {
    try {
      await _api.deleteThread(threadId);
      if (_activeThreadId == threadId) {
        setState(() { _activeThreadId = null; _messages = []; });
      }
      _loadThreads();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Delete failed: $e')),
        );
      }
    }
  }

  Future<void> _renameThread(String threadId, String newTitle) async {
    try {
      await _api.renameThread(threadId, newTitle);
      _loadThreads();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Rename failed: $e')),
        );
      }
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _openSettings() {
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const SettingsScreen()),
    );
  }

  // ── Build ─────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final isWide = MediaQuery.of(context).size.width > 768;

    return Scaffold(
      body: Row(
        children: [
          // Sidebar
          if (_sidebarOpen && isWide)
            Sidebar(
              threads: _threads,
              activeThreadId: _activeThreadId,
              isLoading: _isLoadingThreads,
              onThreadTap: _loadThread,
              onNewChat: _startNewChat,
              onDelete: _deleteThread,
              onRename: _renameThread,
              onSettings: _openSettings,
            ),

          // Main chat area
          Expanded(
            child: FadeTransition(
              opacity: _fadeAnimation,
              child: Column(
                children: [
                  _buildTopBar(isWide),
                  Expanded(child: _buildChatArea()),
                  ChatInput(
                    onSend: _sendMessage,
                    isSending: _isSending,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),

      // Mobile drawer
      drawer: !isWide
          ? Drawer(
              backgroundColor: const Color(0xFF0D0D12),
              child: SafeArea(
                child: Sidebar(
                  threads: _threads,
                  activeThreadId: _activeThreadId,
                  isLoading: _isLoadingThreads,
                  onThreadTap: (id) {
                    Navigator.pop(context);
                    _loadThread(id);
                  },
                  onNewChat: () {
                    Navigator.pop(context);
                    _startNewChat();
                  },
                  onDelete: _deleteThread,
                  onRename: _renameThread,
                  onSettings: () {
                    Navigator.pop(context);
                    _openSettings();
                  },
                ),
              ),
            )
          : null,
    );
  }

  Widget _buildTopBar(bool isWide) {
    return Container(
      height: 56,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      decoration: BoxDecoration(
        color: const Color(0xFF0D0D12),
        border: Border(
          bottom: BorderSide(color: Colors.white.withValues(alpha: 0.06)),
        ),
      ),
      child: Row(
        children: [
          if (!isWide)
            IconButton(
              icon: const Icon(Icons.menu_rounded, color: Color(0xFFA1A1AA)),
              onPressed: () => Scaffold.of(context).openDrawer(),
            ),
          if (isWide)
            IconButton(
              icon: Icon(
                _sidebarOpen ? Icons.menu_open_rounded : Icons.menu_rounded,
                color: const Color(0xFFA1A1AA),
                size: 20,
              ),
              onPressed: () => setState(() => _sidebarOpen = !_sidebarOpen),
              tooltip: _sidebarOpen ? 'Hide sidebar' : 'Show sidebar',
            ),
          const SizedBox(width: 8),
          Text(
            'ThreadBot',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w600,
              color: Colors.white.withValues(alpha: 0.9),
            ),
          ),
          if (_activeThreadId != null) ...[
            const SizedBox(width: 8),
            Container(
              width: 4,
              height: 4,
              decoration: BoxDecoration(
                color: const Color(0xFF8B5CF6),
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                _threads.where((t) => t.id == _activeThreadId).firstOrNull?.title ?? 'Thread',
                style: TextStyle(
                  fontSize: 14,
                  color: Colors.white.withValues(alpha: 0.5),
                ),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ] else
            const Spacer(),
        ],
      ),
    );
  }

  Widget _buildChatArea() {
    if (_isLoadingMessages) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 32,
              height: 32,
              child: CircularProgressIndicator(
                strokeWidth: 2.5,
                valueColor: AlwaysStoppedAnimation(Color(0xFF8B5CF6)),
              ),
            ),
            SizedBox(height: 16),
            Text('Loading conversation...', style: TextStyle(color: Color(0xFF71717A))),
          ],
        ),
      );
    }

    if (_error != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, size: 48, color: Colors.red.shade400),
            const SizedBox(height: 12),
            Text(_error!, style: TextStyle(color: Colors.red.shade300)),
            const SizedBox(height: 16),
            FilledButton.tonal(
              onPressed: _activeThreadId != null ? () => _loadThread(_activeThreadId!) : _loadThreads,
              child: const Text('Retry'),
            ),
          ],
        ),
      );
    }

    if (_messages.isEmpty && _activeThreadId == null) {
      return _buildWelcomeScreen();
    }

    return ChatMessageList(
      messages: _messages,
      scrollController: _scrollController,
      isSending: _isSending,
    );
  }

  Widget _buildWelcomeScreen() {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Glowing logo
          Container(
            width: 80,
            height: 80,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              gradient: const LinearGradient(
                colors: [Color(0xFF8B5CF6), Color(0xFF6366F1)],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              boxShadow: [
                BoxShadow(
                  color: const Color(0xFF8B5CF6).withValues(alpha: 0.3),
                  blurRadius: 32,
                  spreadRadius: 4,
                ),
              ],
            ),
            child: const Icon(Icons.auto_awesome, size: 36, color: Colors.white),
          ),
          const SizedBox(height: 24),
          const Text(
            'What can I help you with?',
            style: TextStyle(
              fontSize: 28,
              fontWeight: FontWeight.w600,
              color: Color(0xFFE4E4E7),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'Start a conversation or select a thread from the sidebar',
            style: TextStyle(
              fontSize: 15,
              color: Colors.white.withValues(alpha: 0.4),
            ),
          ),
          const SizedBox(height: 40),

          // Quick prompt suggestions
          Wrap(
            spacing: 12,
            runSpacing: 12,
            alignment: WrapAlignment.center,
            children: [
              _buildSuggestionChip('Explain quantum computing', Icons.science_outlined),
              _buildSuggestionChip('Write a Python script', Icons.code_outlined),
              _buildSuggestionChip('Plan a trip to Japan', Icons.flight_takeoff_outlined),
              _buildSuggestionChip('Debug my code', Icons.bug_report_outlined),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSuggestionChip(String text, IconData icon) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => _sendMessage(text),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
            color: Colors.white.withValues(alpha: 0.03),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 16, color: const Color(0xFF8B5CF6)),
              const SizedBox(width: 8),
              Text(
                text,
                style: TextStyle(
                  fontSize: 13,
                  color: Colors.white.withValues(alpha: 0.7),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
