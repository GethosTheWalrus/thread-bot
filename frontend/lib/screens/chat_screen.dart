import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:threadbot/models/message.dart';
import 'package:threadbot/models/thread.dart';
import 'package:threadbot/services/api_service.dart';
import 'package:threadbot/widgets/chat_message_list.dart';
import 'package:threadbot/widgets/chat_input.dart';
import 'package:threadbot/widgets/sidebar.dart';
import 'package:threadbot/screens/settings_screen.dart';
import 'package:threadbot/screens/mcp_screen.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> with TickerProviderStateMixin {
  final ApiService _api = ApiService();
  final ScrollController _scrollController = ScrollController();
  // No GlobalKey needed — use Builder + Scaffold.of() for drawer access

  // State
  List<ThreadListItem> _threads = [];
  String? _activeThreadId;
  List<Message> _messages = [];
  bool _isLoadingThreads = false;
  bool _isLoadingMessages = false;
  bool _isSending = false;
  String? _error;
  bool _sidebarOpen = true;
  bool _hasToolOverrides = false;
  bool _isAtBottom = true; // auto-scroll when anchored to bottom

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
    _scrollController.addListener(_onScroll);
    _loadThreads();
  }

  @override
  void dispose() {
    _fadeController.dispose();
    _scrollController.removeListener(_onScroll);
    _scrollController.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (!_scrollController.hasClients) return;
    final pos = _scrollController.position;
    // Consider "at bottom" if within 80px of the max extent
    final atBottom = pos.pixels >= pos.maxScrollExtent - 80;
    if (atBottom != _isAtBottom) {
      _isAtBottom = atBottom;
    }
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
    setState(() { _isLoadingMessages = true; _activeThreadId = threadId; _error = null; _hasToolOverrides = false; });
    try {
      final thread = await _api.getThread(threadId);
      if (mounted) {
        setState(() { _messages = thread.messages; _isLoadingMessages = false; });
        _scrollToBottom(force: true);

        // Check if this thread has any tool overrides
        _loadToolOverrideStatus(threadId);

        // If this thread is still generating (e.g., page was refreshed mid-response),
        // reconnect to the in-progress stream.
        if (thread.isGenerating) {
          _reconnectToStream(threadId);
        }
      }
    } catch (e) {
      if (mounted) setState(() { _error = 'Failed to load thread'; _isLoadingMessages = false; });
    }
  }

  Future<void> _loadToolOverrideStatus(String threadId) async {
    try {
      final data = await _api.getThreadToolOverrides(threadId);
      final overrides = data['overrides'] as List<dynamic>? ?? [];
      if (mounted) {
        setState(() => _hasToolOverrides = overrides.any((o) => o['enabled'] == false));
      }
    } catch (_) {
      // Non-critical — don't show error
    }
  }

  /// Silently reload messages from DB without showing a loading spinner.
  /// Called after [DONE] when all messages are guaranteed persisted.
  Future<void> _reloadThreadSilently() async {
    if (_activeThreadId == null) return;
    try {
      final thread = await _api.getThread(_activeThreadId!);
      if (mounted) {
        setState(() { _messages = thread.messages; });
        _scrollToBottom();
      }
    } catch (_) {
      // Silent — keep temp messages visible if reload fails
    }
  }

  /// Reconnect to an in-progress generation stream after page refresh.
  ///
  /// Removes only the messages after the last user message (the current
  /// generation's partial results), adds a placeholder, and replays buffered
  /// events.  Older conversation history is preserved.
  Future<void> _reconnectToStream(String threadId) async {
    if (_isSending) return;

    final tempIds = <String>[];

    // Remove only the *current* generation's non-user/system messages (after
    // the last user message).  The stream buffer only replays events for the
    // active generation, so older assistant/tool messages from the DB must be
    // kept or the conversation history disappears on refresh.
    setState(() {
      _isSending = true;
      final lastUserIdx = _messages.lastIndexWhere((m) => m.role == 'user');
      if (lastUserIdx >= 0 && lastUserIdx < _messages.length - 1) {
        _messages.removeRange(lastUserIdx + 1, _messages.length);
      }
    });

    // Add a placeholder assistant message for streaming tokens
    final placeholderId = 'temp-ast-${DateTime.now().millisecondsSinceEpoch}';
    tempIds.add(placeholderId);
    setState(() {
      _messages.add(Message(
        id: placeholderId,
        threadId: threadId,
        role: 'assistant',
        content: '',
        createdAt: DateTime.now(),
      ));
    });
    _scrollToBottom(force: true);

    try {
      final stream = _api.reconnectStream(threadId);
      await _processStreamChunks(stream, tempIds, skipHeader: true);

      if (mounted) {
        if (_activeThreadId != null) {
          await _reloadThreadSilently();
        }
        setState(() { _isSending = false; });
        _loadThreads();
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _messages.removeWhere((m) => tempIds.contains(m.id));
          _isSending = false;
        });
        // Silently fail — at least the DB messages are shown
      }
    }
  }

  /// Process a stream of chunks, parsing JSON events and handling them.
  /// Shared between [_sendMessage] and [_reconnectToStream].
  ///
  /// When [skipHeader] is false (default), expects a `THREAD_ID:<id>\n\n` header
  /// as the first chunk. When true (reconnect), skips header processing.
  Future<void> _processStreamChunks(
    Stream<String> stream,
    List<String> tempIds, {
    bool skipHeader = false,
  }) async {
    String headerBuffer = "";
    bool headerProcessed = skipHeader;
    String chunkBuffer = "";

    await for (var chunk in stream) {
      if (!mounted) break;

      if (!headerProcessed) {
        headerBuffer += chunk;
        if (headerBuffer.contains("\n\n")) {
          final parts = headerBuffer.split("\n\n");
          final headerPart = parts[0];
          if (headerPart.startsWith("THREAD_ID:")) {
            final newId = headerPart.substring(10).trim();
            if (_activeThreadId == null || _activeThreadId != newId) {
              setState(() => _activeThreadId = newId);
            }
          }
          headerProcessed = true;
          chunk = parts.length > 1 ? parts.sublist(1).join("\n\n") : "";
        } else {
          continue;
        }
      }

      if (chunk == "[DONE]") break;
      if (chunk.startsWith("[ERROR]")) {
        setState(() => _error = chunk.substring(7));
        break;
      }

      // Remove null heartbeats
      chunk = chunk.replaceAll("\x00", "");
      if (chunk.isEmpty) continue;

      // Buffer chunks and try to parse JSON events
      chunkBuffer += chunk;

      // Try to parse all complete JSON objects from the buffer
      while (chunkBuffer.isNotEmpty) {
        // Check for sentinels first
        if (chunkBuffer.startsWith("[DONE]")) {
          chunkBuffer = chunkBuffer.substring(6);
          break;
        }
        if (chunkBuffer.startsWith("[ERROR]")) {
          setState(() => _error = chunkBuffer.substring(7));
          chunkBuffer = "";
          break;
        }

        // Try to find a complete JSON object
        if (!chunkBuffer.startsWith("{")) {
          final nextBrace = chunkBuffer.indexOf("{");
          if (nextBrace == -1) {
            chunkBuffer = "";
            break;
          }
          chunkBuffer = chunkBuffer.substring(nextBrace);
        }

        // Try to parse JSON from the start of the buffer
        Map<String, dynamic>? event;
        int consumed = 0;
        try {
          event = jsonDecode(chunkBuffer) as Map<String, dynamic>;
          consumed = chunkBuffer.length;
        } catch (_) {
          int depth = 0;
          int? endPos;
          for (int i = 0; i < chunkBuffer.length; i++) {
            if (chunkBuffer[i] == '{') depth++;
            if (chunkBuffer[i] == '}') depth--;
            if (depth == 0) {
              endPos = i + 1;
              break;
            }
          }
          if (endPos != null) {
            try {
              event = jsonDecode(chunkBuffer.substring(0, endPos)) as Map<String, dynamic>;
              consumed = endPos;
            } catch (_) {
              break;
            }
          } else {
            break;
          }
        }

        if (event == null) break;
        chunkBuffer = chunkBuffer.substring(consumed);

        _handleStreamEvent(event, tempIds);
        _scrollToBottom();
      }
    }
  }

  void _showToolOverrides() {
    if (_activeThreadId == null) return;
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xFF16161E),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) => _ToolOverridesSheet(
        threadId: _activeThreadId!,
        api: _api,
        onChanged: () => _loadToolOverrideStatus(_activeThreadId!),
      ),
    );
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
    _scrollToBottom(force: true);

    // Track temporary message IDs for cleanup on reload
    final tempIds = <String>[optimisticMsg.id];

    // Add a placeholder assistant message so the loading shimmer appears immediately
    final placeholderId = 'temp-ast-${DateTime.now().millisecondsSinceEpoch}';
    tempIds.add(placeholderId);
    setState(() {
      _messages.add(Message(
        id: placeholderId,
        threadId: _activeThreadId ?? '',
        role: 'assistant',
        content: '',
        createdAt: DateTime.now(),
      ));
    });
    _scrollToBottom(force: true);

    try {
      final stream = _api.sendMessageStream(content, threadId: _activeThreadId);
      await _processStreamChunks(stream, tempIds);

      // [DONE] received — DB is guaranteed to have all messages (including
      // the final assistant response). Do one clean reload.
      if (mounted) {
        if (_activeThreadId != null) {
          await _reloadThreadSilently();
        }
        setState(() {
          _isSending = false;
        });
        _loadThreads();
      }
    } catch (e) {
      if (mounted) {
        // Remove all temporary messages on error
        setState(() {
          _messages.removeWhere((m) => tempIds.contains(m.id));
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

  /// Handle a single structured JSON event from the stream.
  void _handleStreamEvent(Map<String, dynamic> event, List<String> tempIds) {
    final type = event['type'] as String?;
    final content = event['content'] as String? ?? '';

    switch (type) {
      case 'thinking':
        final id = 'temp-thinking-${DateTime.now().millisecondsSinceEpoch}';
        tempIds.add(id);
        setState(() {
          // Insert before the placeholder assistant message so order is preserved
          final placeholderIdx = _messages.indexWhere(
            (m) => m.id.startsWith('temp-ast-') && m.content.isEmpty,
          );
          final msg = Message(
            id: id,
            threadId: _activeThreadId ?? '',
            role: 'thinking',
            content: content,
            createdAt: DateTime.now(),
          );
          if (placeholderIdx >= 0) {
            _messages.insert(placeholderIdx, msg);
          } else {
            _messages.add(msg);
          }
        });
        break;

      case 'tool_call':
        final id = 'temp-tc-${DateTime.now().millisecondsSinceEpoch}';
        tempIds.add(id);
        final toolCalls = event['tool_calls'] as List<dynamic>?;
        setState(() {
          final placeholderIdx = _messages.indexWhere(
            (m) => m.id.startsWith('temp-ast-') && m.content.isEmpty,
          );
          final msg = Message(
            id: id,
            threadId: _activeThreadId ?? '',
            role: 'tool_call',
            content: content,
            createdAt: DateTime.now(),
            metadata: toolCalls != null ? {'tool_calls': toolCalls} : null,
          );
          if (placeholderIdx >= 0) {
            _messages.insert(placeholderIdx, msg);
          } else {
            _messages.add(msg);
          }
        });
        break;

      case 'tool_result':
        final tool = event['tool'] as String? ?? 'Tool';
        final success = event['success'] as bool? ?? true;
        final id = 'temp-tr-${DateTime.now().millisecondsSinceEpoch}';
        tempIds.add(id);
        setState(() {
          final placeholderIdx = _messages.indexWhere(
            (m) => m.id.startsWith('temp-ast-') && m.content.isEmpty,
          );
          final msg = Message(
            id: id,
            threadId: _activeThreadId ?? '',
            role: 'tool_result',
            content: content,
            createdAt: DateTime.now(),
            metadata: {
              'tool_name': tool,
              'success': success,
            },
          );
          if (placeholderIdx >= 0) {
            _messages.insert(placeholderIdx, msg);
          } else {
            _messages.add(msg);
          }
        });
        break;

      case 'token':
        // Streaming token — append to the placeholder assistant message
        setState(() {
          final placeholder = _messages.where(
            (m) => m.id.startsWith('temp-ast-'),
          ).firstOrNull;
          if (placeholder != null) {
            placeholder.content += content;
          }
        });
        break;

      case 'text':
        // Full text fallback (max-iterations safety, or non-streaming path)
        setState(() {
          final placeholder = _messages.where(
            (m) => m.id.startsWith('temp-ast-'),
          ).firstOrNull;
          if (placeholder != null) {
            // Only replace if streaming hasn't already filled it
            if (placeholder.content.isEmpty) {
              placeholder.content = content;
            }
          } else {
            final id = 'temp-ast-${DateTime.now().millisecondsSinceEpoch}';
            tempIds.add(id);
            _messages.add(Message(
              id: id,
              threadId: _activeThreadId ?? '',
              role: 'assistant',
              content: content,
              createdAt: DateTime.now(),
            ));
          }
        });
        break;

      case 'title':
        // Update the thread title in the sidebar immediately
        setState(() {
          final thread = _threads.where((t) => t.id == _activeThreadId).firstOrNull;
          if (thread != null) {
            thread.title = content;
          }
        });
        break;
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

  Future<void> _deleteAllThreads() async {
    try {
      await _api.deleteAllThreads();
      setState(() { _activeThreadId = null; _messages = []; });
      _loadThreads();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Failed to clear conversations: $e')),
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

  void _scrollToBottom({bool force = false}) {
    if (!force && !_isAtBottom) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
        _isAtBottom = true;
      }
    });
  }

  void _openMCP() {
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => const MCPScreen()),
    );
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
      // key not needed — Builder provides scaffold context for drawer
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
              onDeleteAll: _deleteAllThreads,
              onMCP: _openMCP,
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
                    onToolsPressed: _activeThreadId != null ? _showToolOverrides : null,
                    hasToolOverrides: _hasToolOverrides,
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
                  onDeleteAll: _deleteAllThreads,
                  onMCP: () {
                    Navigator.pop(context);
                    _openMCP();
                  },
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
            Builder(
              builder: (scaffoldContext) => IconButton(
                icon: const Icon(Icons.menu_rounded, color: Color(0xFFA1A1AA)),
                onPressed: () => Scaffold.of(scaffoldContext).openDrawer(),
              ),
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
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 24),
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
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 28,
                fontWeight: FontWeight.w600,
                color: Color(0xFFE4E4E7),
              ),
            ),
            const SizedBox(height: 8),
            Text(
              'Start a conversation or select a thread from the sidebar',
              textAlign: TextAlign.center,
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


// ── Tool Overrides Bottom Sheet ──────────────────────────────────────────────

class _ToolOverridesSheet extends StatefulWidget {
  final String threadId;
  final ApiService api;
  final VoidCallback onChanged;

  const _ToolOverridesSheet({
    required this.threadId,
    required this.api,
    required this.onChanged,
  });

  @override
  State<_ToolOverridesSheet> createState() => _ToolOverridesSheetState();
}

class _ToolOverridesSheetState extends State<_ToolOverridesSheet> {
  bool _isLoading = true;
  bool _isSaving = false;
  List<_ServerState> _servers = [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final data = await widget.api.getThreadToolOverrides(widget.threadId);
      final servers = (data['servers'] as List<dynamic>? ?? []);
      final overrides = (data['overrides'] as List<dynamic>? ?? []);

      // Build override lookup
      final overrideMap = <String, bool>{};       // "server_id" -> enabled
      final toolOverrideMap = <String, bool>{};   // "server_id:tool_name" -> enabled
      for (final o in overrides) {
        final sid = o['server_id'] as String;
        final toolName = o['tool_name'] as String?;
        if (toolName == null) {
          overrideMap[sid] = o['enabled'] as bool;
        } else {
          toolOverrideMap['$sid:$toolName'] = o['enabled'] as bool;
        }
      }

      final serverStates = servers.map((s) {
        final sid = s['id'] as String;
        final tools = (s['tools'] as List<dynamic>? ?? []).map((t) {
          final tname = t['name'] as String;
          return _ToolState(
            name: tname,
            description: t['description'] as String? ?? '',
            enabled: toolOverrideMap['$sid:$tname'] ?? overrideMap[sid] ?? true,
          );
        }).toList();

        // Server is enabled if any tool is enabled (or no server-level override)
        final serverEnabled = overrideMap[sid] ?? true;

        return _ServerState(
          id: sid,
          name: s['name'] as String,
          enabled: serverEnabled,
          tools: tools,
          expanded: false,
        );
      }).toList();

      if (mounted) setState(() { _servers = serverStates; _isLoading = false; });
    } catch (e) {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _save() async {
    setState(() => _isSaving = true);
    try {
      final overrides = <Map<String, dynamic>>[];
      for (final server in _servers) {
        if (!server.enabled) {
          // Server-level disable
          overrides.add({
            'server_id': server.id,
            'tool_name': null,
            'enabled': false,
          });
        } else {
          // Check for individual tool disables
          for (final tool in server.tools) {
            if (!tool.enabled) {
              overrides.add({
                'server_id': server.id,
                'tool_name': tool.name,
                'enabled': false,
              });
            }
          }
        }
      }
      await widget.api.setThreadToolOverrides(widget.threadId, overrides);
      widget.onChanged();
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to save: $e'),
            backgroundColor: Colors.red.shade800,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isSaving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final maxHeight = MediaQuery.of(context).size.height * 0.7;
    return ConstrainedBox(
      constraints: BoxConstraints(maxHeight: maxHeight),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Handle bar
          Padding(
            padding: const EdgeInsets.only(top: 12, bottom: 8),
            child: Container(
              width: 36,
              height: 4,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(2),
                color: Colors.white.withValues(alpha: 0.2),
              ),
            ),
          ),
          // Header
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
            child: Row(
              children: [
                const Icon(Icons.build_outlined, size: 18, color: Color(0xFF8B5CF6)),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    'Thread Tools',
                    style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                  ),
                ),
                FilledButton(
                  onPressed: _isSaving ? null : _save,
                  style: FilledButton.styleFrom(
                    backgroundColor: const Color(0xFF8B5CF6),
                    foregroundColor: Colors.white,
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                  ),
                  child: _isSaving
                      ? const SizedBox(
                          width: 14, height: 14,
                          child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                        )
                      : const Text('Save', style: TextStyle(fontSize: 13)),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: Text(
              'Enable or disable MCP servers and individual tools for this thread.',
              style: TextStyle(fontSize: 12, color: Colors.white.withValues(alpha: 0.4)),
            ),
          ),
          const SizedBox(height: 12),
          // Server list
          if (_isLoading)
            const Padding(
              padding: EdgeInsets.all(32),
              child: CircularProgressIndicator(
                valueColor: AlwaysStoppedAnimation(Color(0xFF8B5CF6)),
              ),
            )
          else if (_servers.isEmpty)
            Padding(
              padding: const EdgeInsets.all(32),
              child: Text(
                'No active MCP servers configured.',
                style: TextStyle(color: Colors.white.withValues(alpha: 0.4)),
              ),
            )
          else
            Flexible(
              child: ListView.builder(
                shrinkWrap: true,
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
                itemCount: _servers.length,
                itemBuilder: (context, index) => _buildServerTile(_servers[index]),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildServerTile(_ServerState server) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(12),
        color: Colors.white.withValues(alpha: 0.03),
        border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
      ),
      child: Column(
        children: [
          // Server header with toggle
          InkWell(
            borderRadius: const BorderRadius.vertical(top: Radius.circular(12)),
            onTap: () => setState(() => server.expanded = !server.expanded),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              child: Row(
                children: [
                  Icon(
                    server.expanded ? Icons.expand_less : Icons.expand_more,
                    size: 18,
                    color: Colors.white.withValues(alpha: 0.4),
                  ),
                  const SizedBox(width: 8),
                  Container(
                    width: 28,
                    height: 28,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(7),
                      gradient: const LinearGradient(
                        colors: [Color(0xFF3B82F6), Color(0xFF6366F1)],
                      ),
                    ),
                    child: const Icon(Icons.dns_rounded, size: 14, color: Colors.white),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          server.name,
                          style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w500),
                        ),
                        Text(
                          '${server.tools.length} tool${server.tools.length == 1 ? '' : 's'}',
                          style: TextStyle(
                            fontSize: 11,
                            color: Colors.white.withValues(alpha: 0.4),
                          ),
                        ),
                      ],
                    ),
                  ),
                  Switch(
                    value: server.enabled,
                    onChanged: (v) {
                      setState(() {
                        server.enabled = v;
                        // When toggling server, also toggle all its tools
                        for (final t in server.tools) {
                          t.enabled = v;
                        }
                      });
                    },
                    activeColor: const Color(0xFF8B5CF6),
                    activeTrackColor: const Color(0xFF8B5CF6).withValues(alpha: 0.3),
                    inactiveThumbColor: Colors.white.withValues(alpha: 0.3),
                    inactiveTrackColor: Colors.white.withValues(alpha: 0.08),
                  ),
                ],
              ),
            ),
          ),
          // Expanded tool list
          if (server.expanded && server.tools.isNotEmpty)
            Container(
              decoration: BoxDecoration(
                border: Border(
                  top: BorderSide(color: Colors.white.withValues(alpha: 0.06)),
                ),
              ),
              child: Column(
                children: server.tools.map((tool) => _buildToolTile(server, tool)).toList(),
              ),
            ),
        ],
      ),
    );
  }

  Widget _buildToolTile(_ServerState server, _ToolState tool) {
    return Padding(
      padding: const EdgeInsets.only(left: 50, right: 14),
      child: Row(
        children: [
          Icon(
            Icons.build_rounded,
            size: 12,
            color: tool.enabled
                ? const Color(0xFF3B82F6).withValues(alpha: 0.6)
                : Colors.white.withValues(alpha: 0.15),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  tool.name,
                  style: TextStyle(
                    fontSize: 13,
                    color: tool.enabled
                        ? Colors.white.withValues(alpha: 0.8)
                        : Colors.white.withValues(alpha: 0.3),
                  ),
                ),
                if (tool.description.isNotEmpty)
                  Text(
                    tool.description,
                    style: TextStyle(
                      fontSize: 11,
                      color: Colors.white.withValues(alpha: 0.3),
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
              ],
            ),
          ),
          Switch(
            value: server.enabled && tool.enabled,
            onChanged: server.enabled
                ? (v) => setState(() => tool.enabled = v)
                : null,
            activeColor: const Color(0xFF8B5CF6),
            activeTrackColor: const Color(0xFF8B5CF6).withValues(alpha: 0.3),
            inactiveThumbColor: Colors.white.withValues(alpha: 0.3),
            inactiveTrackColor: Colors.white.withValues(alpha: 0.08),
          ),
        ],
      ),
    );
  }
}

// Helper state classes for the tool overrides sheet
class _ServerState {
  final String id;
  final String name;
  bool enabled;
  final List<_ToolState> tools;
  bool expanded;

  _ServerState({
    required this.id,
    required this.name,
    required this.enabled,
    required this.tools,
    required this.expanded,
  });
}

class _ToolState {
  final String name;
  final String description;
  bool enabled;

  _ToolState({
    required this.name,
    required this.description,
    required this.enabled,
  });
}
