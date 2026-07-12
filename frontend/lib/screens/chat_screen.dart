import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:threadbot/models/message.dart';
import 'package:threadbot/models/thread.dart';
import 'package:threadbot/services/api_service.dart';
import 'package:threadbot/widgets/chat_message_list.dart';
import 'package:threadbot/widgets/threadbot_avatar.dart';
import 'package:threadbot/widgets/chat_input.dart';
import 'package:threadbot/widgets/sidebar.dart';

class ChatScreen extends StatefulWidget {
  final String? initialThreadId;
  const ChatScreen({super.key, this.initialThreadId});

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
  bool _hasLlmOverrides = false;
  DiscordThreadLink? _discordLink;
  ReachyBinding? _reachyBinding;
  bool _isTogglingReachy = false;
  List<Map<String, dynamic>>? _pendingToolOverrides;
  bool _isAtBottom = true; // auto-scroll when anchored to bottom
  int _contextEstimatedTokens = 0;
  int _contextWindow = 8192;
  Timer? _threadRefreshTimer;
  WebSocketChannel? _broadcastChannel;
  bool _continuePromptOpen = false;

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
    _loadThreads().then((_) {
      if (widget.initialThreadId != null) {
        _loadThread(widget.initialThreadId!);
      }
    });
    _loadReachyBinding();
    _threadRefreshTimer = Timer.periodic(
      const Duration(seconds: 10),
      (_) => _loadThreads(silent: true),
    );
    _subscribeToBroadcast();
  }

  void _subscribeToBroadcast() {
    _broadcastChannel = _api.subscribeBroadcast();
    _broadcastChannel?.stream.listen(
      (data) {
        final event = jsonDecode(data as String) as Map<String, dynamic>;
        if (event['type'] == 'thread_updated') {
          if (mounted) {
            setState(() {
              final thread = _threads.firstWhere(
                (t) => t.id == event['thread_id'],
                orElse: () => ThreadListItem(
                  id: '',
                  title: '',
                  createdAt: DateTime.now(),
                  updatedAt: DateTime.now(),
                  messageCount: 0,
                ),
              );
              if (thread.id.isNotEmpty) {
                // Thread exists — just refresh the thread list
              }
            });
            _loadThreads(silent: true);
          }
        }
      },
      onError: (_) {},
      onDone: () => _subscribeToBroadcast(),
    );
  }

  @override
  void dispose() {
    _broadcastChannel?.sink.close();
    _threadRefreshTimer?.cancel();
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

  Future<void> _loadThreads({bool silent = false}) async {
    if (!silent) setState(() => _isLoadingThreads = true);
    try {
      final threads = await _api.getThreads();
      if (mounted) {
        setState(() {
          _threads = threads;
          if (!silent) _isLoadingThreads = false;
        });
      }
    } catch (e) {
      if (mounted && !silent) {
        setState(() {
          _error = 'Failed to load threads';
          _isLoadingThreads = false;
        });
      }
    }
  }

  Future<void> _loadReachyBinding() async {
    try {
      final binding = await _api.getReachyBinding();
      if (mounted) {
        setState(() => _reachyBinding = binding);
      }
    } catch (_) {
      // Non-critical: the chat still works without Reachy status.
    }
  }

  Future<void> _loadThread(String threadId) async {
    setState(() {
      _isLoadingMessages = true;
      _activeThreadId = threadId;
      _error = null;
      _hasToolOverrides = false;
      _hasLlmOverrides = false;
    });
    try {
      SystemNavigator.routeInformationUpdated(
        uri: Uri.parse('/thread/$threadId'),
      );
      final thread = await _api.getThread(threadId);
      if (mounted) {
        setState(() {
          _messages = thread.messages;
          _discordLink = thread.discordLink;
          _reachyBinding = ReachyBinding(
            enabled: _reachyBinding?.enabled ?? false,
            threadId: thread.reachyConnected
                ? thread.id
                : _reachyBinding?.threadId,
            threadTitle: thread.reachyConnected
                ? thread.title
                : _reachyBinding?.threadTitle,
            wakeWord: _reachyBinding?.wakeWord ?? 'Reachy',
            taskQueue: _reachyBinding?.taskQueue ?? 'reachy-local',
          );
          _contextEstimatedTokens = thread.estimatedTokens;
          _contextWindow = thread.contextWindow;
          _isLoadingMessages = false;
        });
        _scrollToBottom(force: true);

        // Check if this thread has any tool overrides
        _loadToolOverrideStatus(threadId);
        _loadLlmOverrideStatus(threadId);
        _loadReachyBinding();

        // If this thread is still generating (e.g., page was refreshed mid-response),
        // reconnect to the in-progress stream.
        if (thread.isGenerating) {
          _reconnectToStream(threadId);
        }
      }
    } catch (e) {
      if (mounted)
        setState(() {
          _error = 'Failed to load thread';
          _isLoadingMessages = false;
        });
    }
  }

  Future<void> _loadToolOverrideStatus(String threadId) async {
    try {
      final data = await _api.getThreadToolOverrides(threadId);
      final overrides = data['overrides'] as List<dynamic>? ?? [];
      if (mounted) {
        setState(
          () => _hasToolOverrides = overrides.any((o) => o['enabled'] == false),
        );
      }
    } catch (_) {
      // Non-critical — don't show error
    }
  }

  Future<void> _loadLlmOverrideStatus(String threadId) async {
    try {
      final overrides = await _api.getThreadLlmOverrides(threadId);
      if (mounted) {
        setState(() => _hasLlmOverrides = !overrides.isEmpty);
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
        setState(() {
          _messages = thread.messages;
          _contextEstimatedTokens = thread.estimatedTokens;
          _contextWindow = thread.contextWindow;
        });
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
      _messages.add(
        Message(
          id: placeholderId,
          threadId: threadId,
          role: 'assistant',
          content: '',
          createdAt: DateTime.now(),
        ),
      );
    });
    _scrollToBottom(force: true);

    try {
      final stream = _api.reconnectStream(threadId);
      await _processStreamChunks(stream, tempIds, skipHeader: true);

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
              SystemNavigator.routeInformationUpdated(
                uri: Uri.parse('/thread/$newId'),
              );
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
        throw Exception(chunk.substring(7));
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
          final errorMsg = chunkBuffer.substring(7);
          chunkBuffer = "";
          throw Exception(errorMsg);
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
              event =
                  jsonDecode(chunkBuffer.substring(0, endPos))
                      as Map<String, dynamic>;
              consumed = endPos;
            } catch (_) {
              break;
            }
          } else {
            break;
          }
        }

        chunkBuffer = chunkBuffer.substring(consumed);

        _handleStreamEvent(event, tempIds);
        _scrollToBottom();
      }
    }
  }

  int _assistantPlaceholderIndex() {
    return _messages.indexWhere((m) => m.id.startsWith('temp-ast-'));
  }

  void _showToolOverrides() {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xFF16161E),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) => _ToolOverridesSheet(
        threadId: _activeThreadId,
        api: _api,
        initialOverrides: _activeThreadId == null
            ? _pendingToolOverrides
            : null,
        onChanged: () {
          if (_activeThreadId != null) {
            _loadToolOverrideStatus(_activeThreadId!);
          }
        },
        onOverridesSelected: (overrides) {
          if (_activeThreadId == null) {
            setState(() {
              _pendingToolOverrides = overrides;
              _hasToolOverrides = overrides.any((o) => o['enabled'] == false);
            });
          }
        },
      ),
    );
  }

  void _showLlmOverrides() {
    final threadId = _activeThreadId;
    if (threadId == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Open a thread first to set per-thread LLM overrides.'),
          behavior: SnackBarBehavior.floating,
        ),
      );
      return;
    }
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xFF16161E),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) => _LlmOverridesSheet(
        threadId: threadId,
        api: _api,
        onChanged: () => _loadLlmOverrideStatus(threadId),
      ),
    );
  }

  Future<void> _toggleReachyBinding() async {
    final threadId = _activeThreadId;
    if (threadId == null || _isTogglingReachy) return;
    setState(() => _isTogglingReachy = true);
    try {
      final isConnected = _reachyBinding?.threadId == threadId;
      final binding = isConnected
          ? await _api.disconnectReachyThread(threadId)
          : await _api.connectReachyThread(threadId);
      if (!mounted) return;
      setState(() => _reachyBinding = binding);
      await _loadThreads(silent: true);
      if (!mounted) return;
      final message = binding.threadId == threadId
          ? 'Reachy connected to this thread'
          : 'Reachy disconnected';
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(message),
          backgroundColor: const Color(0xFF27272A),
          behavior: SnackBarBehavior.floating,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
          ),
        ),
      );
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Reachy binding failed: $e'),
            backgroundColor: Colors.red.shade800,
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isTogglingReachy = false);
    }
  }

  Future<void> _sendMessage(
    String content, [
    List<String> imageUrls = const [],
  ]) async {
    if (_isSending) return;

    setState(() => _isSending = true);

    final messageMetadata = imageUrls.isNotEmpty
        ? {
            'image_attachments': imageUrls.map((url) => {'url': url}).toList(),
          }
        : null;

    // Optimistic UI: add user message immediately
    final optimisticMsg = Message(
      id: 'temp-${DateTime.now().millisecondsSinceEpoch}',
      threadId: _activeThreadId ?? '',
      role: 'user',
      content: content,
      createdAt: DateTime.now(),
      metadata: messageMetadata,
    );
    setState(() => _messages.add(optimisticMsg));
    _scrollToBottom(force: true);

    // Track temporary message IDs for cleanup on reload
    final tempIds = <String>[optimisticMsg.id];

    // Add a placeholder assistant message so the loading shimmer appears immediately
    final placeholderId = 'temp-ast-${DateTime.now().millisecondsSinceEpoch}';
    tempIds.add(placeholderId);
    setState(() {
      _messages.add(
        Message(
          id: placeholderId,
          threadId: _activeThreadId ?? '',
          role: 'assistant',
          content: '',
          createdAt: DateTime.now(),
        ),
      );
    });
    _scrollToBottom(force: true);

    try {
      final stream = _api.sendMessageStream(
        content,
        threadId: _activeThreadId,
        overrides: _activeThreadId == null ? _pendingToolOverrides : null,
        imageUrls: imageUrls.isEmpty ? null : imageUrls,
      );
      await _processStreamChunks(stream, tempIds);

      // [DONE] received — DB is guaranteed to have all messages (including
      // the final assistant response). Do one clean reload.
      if (mounted) {
        if (_activeThreadId != null) {
          await _reloadThreadSilently();
        }
        setState(() {
          _isSending = false;
          _pendingToolOverrides =
              null; // Clear pending overrides after first message
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
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
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
      case 'retry':
        // A retry means the previous streamed attempt failed. Keep the
        // optimistic user message and assistant placeholder, but clear any
        // partial assistant text/intermediate events from the failed attempt.
        setState(() {
          final keepIds = tempIds.take(2).toSet();
          _messages.removeWhere(
            (m) => tempIds.contains(m.id) && !keepIds.contains(m.id),
          );
          if (tempIds.length > 2) {
            tempIds.removeRange(2, tempIds.length);
          }
          final placeholder = _messages
              .where((m) => m.id.startsWith('temp-ast-'))
              .firstOrNull;
          if (placeholder != null) {
            placeholder.content = '';
          }
        });
        break;

      case 'thinking':
        final id = 'temp-thinking-${DateTime.now().millisecondsSinceEpoch}';
        tempIds.add(id);
        setState(() {
          // Insert before the placeholder assistant message so order is preserved
          final placeholderIdx = _assistantPlaceholderIndex();
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
          final placeholderIdx = _assistantPlaceholderIndex();
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
        // The backend includes any image URL directly in `content` (e.g.
        // "Reachy camera capture saved as <url>"), and the Message model's
        // `generatedMediaAttachments` regex picks it up for inline
        // rendering. We still surface `image_url` on the event for callers
        // that want to handle it explicitly.
        final id = 'temp-tr-${DateTime.now().millisecondsSinceEpoch}';
        tempIds.add(id);
        setState(() {
          final placeholderIdx = _assistantPlaceholderIndex();
          final msg = Message(
            id: id,
            threadId: _activeThreadId ?? '',
            role: 'tool_result',
            content: content,
            createdAt: DateTime.now(),
            metadata: {'tool_name': tool, 'success': success},
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
          final placeholder = _messages
              .where((m) => m.id.startsWith('temp-ast-'))
              .firstOrNull;
          if (placeholder != null) {
            placeholder.content += content;
          }
        });
        break;

      case 'text':
        // Full text fallback (max-iterations safety, or non-streaming path)
        setState(() {
          final placeholder = _messages
              .where((m) => m.id.startsWith('temp-ast-'))
              .firstOrNull;
          if (placeholder != null) {
            // Only replace if streaming hasn't already filled it
            if (placeholder.content.isEmpty) {
              placeholder.content = content;
            }
          } else {
            final id = 'temp-ast-${DateTime.now().millisecondsSinceEpoch}';
            tempIds.add(id);
            _messages.add(
              Message(
                id: id,
                threadId: _activeThreadId ?? '',
                role: 'assistant',
                content: content,
                createdAt: DateTime.now(),
              ),
            );
          }
        });
        break;

      case 'title':
        // Update the thread title in the sidebar immediately
        setState(() {
          final eventThreadId =
              event['thread_id'] as String? ?? _activeThreadId;
          final thread = _threads
              .where((t) => t.id == eventThreadId)
              .firstOrNull;
          if (thread != null) {
            thread.title = content;
          }
        });
        _loadThreads(silent: true);
        break;

      case 'compaction':
        final compactedCount = event['compacted_count'] as int? ?? 0;
        final id = 'temp-compact-${DateTime.now().millisecondsSinceEpoch}';
        tempIds.add(id);
        setState(() {
          final placeholderIdx = _assistantPlaceholderIndex();
          final msg = Message(
            id: id,
            threadId: _activeThreadId ?? '',
            role: 'system',
            content: content,
            createdAt: DateTime.now(),
            metadata: {
              'type': 'compaction_event',
              'compacted_count': compactedCount,
            },
          );
          if (placeholderIdx >= 0) {
            _messages.insert(placeholderIdx, msg);
          } else {
            _messages.add(msg);
          }
        });
        break;

      case 'context':
        final estimatedTokens = event['estimated_tokens'] as int? ?? 0;
        final contextWindow = event['context_window'] as int? ?? 8192;
        setState(() {
          _contextEstimatedTokens = estimatedTokens;
          _contextWindow = contextWindow;
        });
        break;

      case 'continue_prompt':
        _showContinuePrompt(event);
        break;
    }
  }

  Future<void> _showContinuePrompt(Map<String, dynamic> event) async {
    if (_continuePromptOpen || !mounted) return;
    final threadId = event['thread_id'] as String? ?? _activeThreadId;
    if (threadId == null) return;

    setState(() => _continuePromptOpen = true);
    final shouldContinue = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        backgroundColor: const Color(0xFF16161E),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
        title: const Text('Continue iterating?'),
        content: Text(
          event['content'] as String? ??
              'ThreadBot hit its tool/turn limit before finishing.',
          style: TextStyle(color: Colors.white.withValues(alpha: 0.72)),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Stop'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Continue'),
          ),
        ],
      ),
    );
    if (!mounted) return;
    try {
      await _api.respondContinue(threadId, shouldContinue ?? false);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to respond: $e'),
            backgroundColor: Colors.red.shade800,
            behavior: SnackBarBehavior.floating,
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _continuePromptOpen = false);
    }
  }

  Future<void> _startRegularNewChat() async {
    SystemNavigator.routeInformationUpdated(uri: Uri.parse('/'));
    setState(() {
      _activeThreadId = null;
      _messages = [];
      _error = null;
      _contextEstimatedTokens = 0;
      _pendingToolOverrides = null;
      _hasToolOverrides = false;
      _hasLlmOverrides = false;
      _discordLink = null;
    });
  }

  Future<void> _startNewChat() async {
    final choice = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: const Color(0xFF16161E),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Center(
                child: Container(
                  width: 36,
                  height: 4,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(2),
                    color: Colors.white.withValues(alpha: 0.2),
                  ),
                ),
              ),
              const SizedBox(height: 18),
              const Text(
                'Start a new thread',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 6),
              Text(
                'Choose where this conversation should live.',
                style: TextStyle(
                  fontSize: 13,
                  color: Colors.white.withValues(alpha: 0.45),
                ),
              ),
              const SizedBox(height: 18),
              _NewThreadChoiceTile(
                icon: Icons.chat_bubble_outline,
                title: 'Regular Thread',
                subtitle: 'Private ThreadBot conversation',
                onTap: () => Navigator.pop(context, 'regular'),
              ),
              const SizedBox(height: 10),
              _NewThreadChoiceTile(
                icon: Icons.forum_outlined,
                title: 'Discord Thread',
                subtitle: 'Create and sync a Discord thread now',
                badgeText: 'D',
                onTap: () => Navigator.pop(context, 'discord'),
              ),
            ],
          ),
        ),
      ),
    );

    if (choice == 'discord') {
      await _startDiscordNewChat();
    } else if (choice == 'regular') {
      await _startRegularNewChat();
    }
  }

  Future<void> _startDiscordNewChat() async {
    try {
      final settings = await _api.getDiscordSettings();
      if (settings['enabled'] != true || settings['has_bot_token'] != true) {
        if (mounted) _showDiscordSetupSnack();
        return;
      }

      final result = await showDialog<Map<String, String?>>(
        context: context,
        builder: (ctx) {
          final nameController = TextEditingController(
            text: 'ThreadBot Thread',
          );
          final guildController = TextEditingController(
            text: settings['guild_id'],
          );
          final channelController = TextEditingController(
            text: settings['channel_id'],
          );
          return AlertDialog(
            backgroundColor: const Color(0xFF1E1E2E),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
            ),
            title: const Text(
              'New Discord Thread',
              style: TextStyle(color: Colors.white),
            ),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  TextField(
                    controller: nameController,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(
                      labelText: 'Discord thread name',
                      labelStyle: TextStyle(color: Colors.white70),
                      filled: true,
                      fillColor: Color(0xFF2A2A3C),
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: guildController,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(
                      labelText: 'Server ID (optional)',
                      labelStyle: TextStyle(color: Colors.white70),
                      filled: true,
                      fillColor: Color(0xFF2A2A3C),
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: channelController,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(
                      labelText: 'Channel ID (optional)',
                      labelStyle: TextStyle(color: Colors.white70),
                      filled: true,
                      fillColor: Color(0xFF2A2A3C),
                      border: OutlineInputBorder(),
                    ),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text(
                  'Cancel',
                  style: TextStyle(color: Colors.white70),
                ),
              ),
              TextButton(
                onPressed: () => Navigator.pop(ctx, {
                  'name': nameController.text,
                  'guildId': guildController.text,
                  'channelId': channelController.text,
                }),
                child: const Text(
                  'Create',
                  style: TextStyle(color: Color(0xFF8B5CF6)),
                ),
              ),
            ],
          );
        },
      );

      if (result == null || !mounted) return;

      final thread = await _api.createThread(title: 'New Thread');
      final link = await _api.shareThreadToDiscord(
        thread.id,
        name: result['name'] ?? 'ThreadBot Thread',
        guildId: result['guildId'],
        channelId: result['channelId'],
      );

      if (!mounted) return;
      SystemNavigator.routeInformationUpdated(
        uri: Uri.parse('/thread/${thread.id}'),
      );
      setState(() {
        _activeThreadId = thread.id;
        _messages = [];
        _error = null;
        _contextEstimatedTokens = 0;
        _pendingToolOverrides = null;
        _hasToolOverrides = false;
        _hasLlmOverrides = false;
        _discordLink = link;
      });
      _loadThreads();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to create Discord thread: $e'),
            backgroundColor: Colors.red.shade800,
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
          ),
        );
      }
    }
  }

  Future<void> _deleteThread(String threadId) async {
    try {
      await _api.deleteThread(threadId);
      if (_activeThreadId == threadId) {
        SystemNavigator.routeInformationUpdated(uri: Uri.parse('/'));
        setState(() {
          _activeThreadId = null;
          _messages = [];
          _discordLink = null;
        });
      }
      _loadThreads();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Delete failed: $e')));
      }
    }
  }

  Future<void> _deleteAllThreads() async {
    try {
      await _api.deleteAllThreads();
      SystemNavigator.routeInformationUpdated(uri: Uri.parse('/'));
      setState(() {
        _activeThreadId = null;
        _messages = [];
        _discordLink = null;
      });
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
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Rename failed: $e')));
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
    Navigator.of(context).pushNamed('/mcp');
  }

  void _openSkills() {
    Navigator.of(context).pushNamed('/skills');
  }

  void _openSettings() {
    Navigator.of(context).pushNamed('/settings');
  }

  Future<void> _toggleDiscordShare() async {
    if (_activeThreadId == null) return;

    try {
      if (_discordLink?.isActive == true) {
        await _api.unshareThreadFromDiscord(_activeThreadId!);
        if (mounted) {
          setState(() => _discordLink = null);
          _loadThreads();
        }
        return;
      }

      final settings = await _api.getDiscordSettings();
      if (settings['enabled'] != true || settings['has_bot_token'] != true) {
        if (mounted) _showDiscordSetupSnack();
        return;
      }

      final title = _threads
          .where((t) => t.id == _activeThreadId)
          .firstOrNull
          ?.title;
      final result = await showDialog<Map<String, String?>>(
        context: context,
        builder: (ctx) {
          final nameController = TextEditingController(
            text: title ?? 'ThreadBot Thread',
          );
          final guildController = TextEditingController(
            text: settings['guild_id'],
          );
          final channelController = TextEditingController(
            text: settings['channel_id'],
          );
          return AlertDialog(
            backgroundColor: const Color(0xFF1E1E2E),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
            ),
            title: const Text(
              'Share Thread to Discord',
              style: TextStyle(color: Colors.white),
            ),
            content: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  TextField(
                    controller: nameController,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(
                      labelText: 'Discord thread name',
                      labelStyle: TextStyle(color: Colors.white70),
                      filled: true,
                      fillColor: Color(0xFF2A2A3C),
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: guildController,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(
                      labelText: 'Server ID (optional)',
                      labelStyle: TextStyle(color: Colors.white70),
                      filled: true,
                      fillColor: Color(0xFF2A2A3C),
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: channelController,
                    style: const TextStyle(color: Colors.white),
                    decoration: const InputDecoration(
                      labelText: 'Channel ID (optional)',
                      labelStyle: TextStyle(color: Colors.white70),
                      filled: true,
                      fillColor: Color(0xFF2A2A3C),
                      border: OutlineInputBorder(),
                    ),
                  ),
                ],
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text(
                  'Cancel',
                  style: TextStyle(color: Colors.white70),
                ),
              ),
              TextButton(
                onPressed: () => Navigator.pop(ctx, {
                  'name': nameController.text,
                  'guildId': guildController.text,
                  'channelId': channelController.text,
                }),
                child: const Text(
                  'Share',
                  style: TextStyle(color: Color(0xFF8B5CF6)),
                ),
              ),
            ],
          );
        },
      );

      if (result == null || !mounted) return;

      final link = await _api.shareThreadToDiscord(
        _activeThreadId!,
        name: result['name'] ?? title,
        guildId: result['guildId'],
        channelId: result['channelId'],
      );
      if (mounted) {
        setState(() => _discordLink = link);
        _loadThreads();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text('Thread shared to Discord'),
            backgroundColor: const Color(0xFF16161E),
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Discord sync failed: $e'),
            backgroundColor: Colors.red.shade800,
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
          ),
        );
      }
    }
  }

  void _showDiscordSetupSnack() {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: const Text('Configure Discord in Settings first'),
        backgroundColor: const Color(0xFF16161E),
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        action: SnackBarAction(label: 'Settings', onPressed: _openSettings),
      ),
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
              onSkills: _openSkills,
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
                    onToolsPressed: _showToolOverrides,
                    hasToolOverrides: _hasToolOverrides,
                    onLlmOverridesPressed: _showLlmOverrides,
                    hasLlmOverrides: _hasLlmOverrides,
                    estimatedTokens: _contextEstimatedTokens,
                    contextWindow: _contextWindow,
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
                  onSkills: () {
                    Navigator.pop(context);
                    _openSkills();
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
                _threads
                        .where((t) => t.id == _activeThreadId)
                        .firstOrNull
                        ?.title ??
                    'Thread',
                style: TextStyle(
                  fontSize: 14,
                  color: Colors.white.withValues(alpha: 0.5),
                ),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            Tooltip(
              message: _discordLink?.isActive == true
                  ? 'Disable Discord sync'
                  : 'Share to Discord',
              child: IconButton(
                onPressed: _toggleDiscordShare,
                icon: _DiscordShareIcon(active: _discordLink?.isActive == true),
              ),
            ),
            Tooltip(
              message: _reachyBinding?.threadId == _activeThreadId
                  ? 'Disconnect Reachy from this thread'
                  : _reachyBinding?.threadId != null
                  ? 'Move Reachy connection to this thread'
                  : 'Connect this thread to Reachy',
              child: IconButton(
                onPressed: _isTogglingReachy ? null : _toggleReachyBinding,
                icon: _ReachyShareIcon(
                  active: _reachyBinding?.threadId == _activeThreadId,
                  busy: _isTogglingReachy,
                ),
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
            Text(
              'Loading conversation...',
              style: TextStyle(color: Color(0xFF71717A)),
            ),
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
              onPressed: _activeThreadId != null
                  ? () => _loadThread(_activeThreadId!)
                  : _loadThreads,
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
            // Glowing 3D Poly-Bot Avatar
            const ThreadbotAvatar(
              size: 200,
              showBackground: false,
              showShadow: true,
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
                _buildSuggestionChip(
                  'Explain quantum computing',
                  Icons.science_outlined,
                ),
                _buildSuggestionChip(
                  'Write a Python script',
                  Icons.code_outlined,
                ),
                _buildSuggestionChip(
                  'Plan a trip to Japan',
                  Icons.flight_takeoff_outlined,
                ),
                _buildSuggestionChip(
                  'Debug my code',
                  Icons.bug_report_outlined,
                ),
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
        onTap: () => _sendMessage(text, const []),
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

class _DiscordShareIcon extends StatelessWidget {
  final bool active;

  const _DiscordShareIcon({required this.active});

  @override
  Widget build(BuildContext context) {
    return Icon(
      Icons.discord,
      size: 14,
      color: active ? Colors.white : Colors.white.withValues(alpha: 0.45),
    );
  }
}

class _ReachyShareIcon extends StatelessWidget {
  final bool active;
  final bool busy;

  const _ReachyShareIcon({required this.active, this.busy = false});

  @override
  Widget build(BuildContext context) {
    if (busy) {
      return SizedBox(
        width: 14,
        height: 14,
        child: CircularProgressIndicator(
          strokeWidth: 2,
          valueColor: AlwaysStoppedAnimation(
            Colors.white.withValues(alpha: 0.7),
          ),
        ),
      );
    }
    return Icon(
      Icons.smart_toy_rounded,
      size: 17,
      color: active
          ? const Color(0xFF34D399)
          : Colors.white.withValues(alpha: 0.45),
    );
  }
}

class _NewThreadChoiceTile extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final String? badgeText;
  final VoidCallback onTap;

  const _NewThreadChoiceTile({
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
    this.badgeText,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(14),
            color: Colors.white.withValues(alpha: 0.03),
            border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
          ),
          child: Row(
            children: [
              Container(
                width: 38,
                height: 38,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(11),
                  gradient: badgeText == null
                      ? const LinearGradient(
                          colors: [Color(0xFF8B5CF6), Color(0xFF6366F1)],
                        )
                      : const LinearGradient(
                          colors: [Color(0xFF5865F2), Color(0xFF4752C4)],
                        ),
                ),
                child: badgeText == null
                    ? Icon(icon, size: 18, color: Colors.white)
                    : Text(
                        badgeText!,
                        style: const TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.w800,
                          color: Colors.white,
                        ),
                      ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      subtitle,
                      style: TextStyle(
                        fontSize: 12,
                        color: Colors.white.withValues(alpha: 0.45),
                      ),
                    ),
                  ],
                ),
              ),
              Icon(
                Icons.chevron_right_rounded,
                color: Colors.white.withValues(alpha: 0.35),
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
  final String? threadId;
  final ApiService api;
  final VoidCallback onChanged;
  final List<Map<String, dynamic>>? initialOverrides;
  final Function(List<Map<String, dynamic>>)? onOverridesSelected;

  const _ToolOverridesSheet({
    required this.threadId,
    required this.api,
    required this.onChanged,
    this.initialOverrides,
    this.onOverridesSelected,
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
      final Map<String, dynamic> data;
      if (widget.threadId != null) {
        data = await widget.api.getThreadToolOverrides(widget.threadId!);
      } else {
        data = await widget.api.getGlobalToolOverrides();
      }

      final servers = (data['servers'] as List<dynamic>? ?? []);
      final overrides = widget.threadId != null
          ? (data['overrides'] as List<dynamic>? ?? [])
          : (widget.initialOverrides ?? []);

      // Build override lookup
      final overrideMap = <String, bool>{}; // "server_id" -> enabled
      final toolOverrideMap =
          <String, bool>{}; // "server_id:tool_name" -> enabled
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

      if (mounted)
        setState(() {
          _servers = serverStates;
          _isLoading = false;
        });
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

      if (widget.threadId != null) {
        await widget.api.setThreadToolOverrides(widget.threadId!, overrides);
        widget.onChanged();
      } else if (widget.onOverridesSelected != null) {
        widget.onOverridesSelected!(overrides);
      }

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
                const Icon(
                  Icons.build_outlined,
                  size: 18,
                  color: Color(0xFF8B5CF6),
                ),
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
                    padding: const EdgeInsets.symmetric(
                      horizontal: 16,
                      vertical: 8,
                    ),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(10),
                    ),
                  ),
                  child: _isSaving
                      ? const SizedBox(
                          width: 14,
                          height: 14,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
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
              style: TextStyle(
                fontSize: 12,
                color: Colors.white.withValues(alpha: 0.4),
              ),
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
                itemBuilder: (context, index) =>
                    _buildServerTile(_servers[index]),
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
                    child: const Icon(
                      Icons.dns_rounded,
                      size: 14,
                      color: Colors.white,
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          server.name,
                          style: const TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.w500,
                          ),
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
                    activeTrackColor: const Color(
                      0xFF8B5CF6,
                    ).withValues(alpha: 0.3),
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
                children: server.tools
                    .map((tool) => _buildToolTile(server, tool))
                    .toList(),
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

class _LlmOverridesSheet extends StatefulWidget {
  final String threadId;
  final ApiService api;
  final VoidCallback? onChanged;

  const _LlmOverridesSheet({
    required this.threadId,
    required this.api,
    this.onChanged,
  });

  @override
  State<_LlmOverridesSheet> createState() => _LlmOverridesSheetState();
}

class _LlmOverridesSheetState extends State<_LlmOverridesSheet> {
  ThreadLlmOverrides? _overrides;
  bool _isLoading = true;
  bool _isSaving = false;
  String? _error;
  final TextEditingController _searchController = TextEditingController();
  String _search = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final overrides = await widget.api.getThreadLlmOverrides(widget.threadId);
      if (!mounted) return;
      setState(() {
        _overrides = overrides;
        _isLoading = false;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _isLoading = false;
      });
    }
  }

  Future<void> _save(Map<String, dynamic> next) async {
    setState(() => _isSaving = true);
    try {
      final updated = await widget.api.setThreadLlmOverrides(
        widget.threadId,
        next,
      );
      if (!mounted) return;
      setState(() {
        _overrides = updated;
        _isSaving = false;
        _error = null;
      });
      widget.onChanged?.call();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _isSaving = false;
      });
    }
  }

  Future<void> _clearAll() async {
    setState(() => _isSaving = true);
    try {
      final updated = await widget.api.clearThreadLlmOverrides(widget.threadId);
      if (!mounted) return;
      setState(() {
        _overrides = updated;
        _isSaving = false;
        _error = null;
      });
      widget.onChanged?.call();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _isSaving = false;
      });
    }
  }

  void _setOverride(String key, dynamic value) {
    final current = Map<String, dynamic>.from(
      _overrides?.overrides ?? const {},
    );
    current[key] = value;
    _save(current);
  }

  void _clearOne(String key) {
    final current = Map<String, dynamic>.from(
      _overrides?.overrides ?? const {},
    );
    current.remove(key);
    if (current.isEmpty) {
      _clearAll();
    } else {
      _save(current);
    }
  }

  @override
  Widget build(BuildContext context) {
    final mediaQuery = MediaQuery.of(context);
    final overrides = _overrides;

    return DraggableScrollableSheet(
      expand: false,
      initialChildSize: 0.9,
      minChildSize: 0.4,
      maxChildSize: 0.95,
      builder: (context, scrollController) {
        return Padding(
          padding: EdgeInsets.only(bottom: mediaQuery.viewInsets.bottom),
          child: Container(
            decoration: const BoxDecoration(
              color: Color(0xFF16161E),
              borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
            ),
            child: Column(
              children: [
                _buildHeader(),
                if (_isLoading)
                  const Padding(
                    padding: EdgeInsets.all(32),
                    child: CircularProgressIndicator(),
                  )
                else if (_error != null)
                  Padding(
                    padding: const EdgeInsets.all(16),
                    child: Text(
                      _error!,
                      style: const TextStyle(color: Colors.redAccent),
                    ),
                  )
                else if (overrides != null)
                  Expanded(child: _buildBody(overrides, scrollController)),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildHeader() {
    final overrides = _overrides;
    final hasAny = overrides != null && overrides.overrides.isNotEmpty;
    return Container(
      padding: const EdgeInsets.fromLTRB(20, 12, 12, 12),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Color(0xFF22222D))),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  'Per-thread LLM overrides',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 18,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              IconButton(
                icon: const Icon(Icons.close, color: Colors.white70),
                onPressed: () => Navigator.of(context).pop(),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            hasAny
                ? '${overrides.overrides.length} override${overrides.overrides.length == 1 ? '' : 's'} set on this thread. Anything not set falls back to the global LLM settings.'
                : 'Anything you set here overrides the global LLM settings for this thread only. Anything you leave unset falls back to the global LLM settings.',
            style: const TextStyle(color: Colors.white54, fontSize: 12),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _searchController,
                  onChanged: (v) =>
                      setState(() => _search = v.trim().toLowerCase()),
                  style: const TextStyle(color: Colors.white, fontSize: 13),
                  decoration: InputDecoration(
                    isDense: true,
                    hintText: 'Search overrides…',
                    hintStyle: const TextStyle(color: Colors.white38),
                    prefixIcon: const Icon(
                      Icons.search,
                      color: Colors.white38,
                      size: 16,
                    ),
                    filled: true,
                    fillColor: const Color(0xFF1E1E2A),
                    contentPadding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 8,
                    ),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: BorderSide.none,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              if (hasAny)
                TextButton.icon(
                  onPressed: _isSaving ? null : _clearAll,
                  icon: const Icon(
                    Icons.clear_all,
                    color: Color(0xFFEF4444),
                    size: 16,
                  ),
                  label: const Text(
                    'Clear all',
                    style: TextStyle(color: Color(0xFFEF4444)),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildBody(
    ThreadLlmOverrides overrides,
    ScrollController scrollController,
  ) {
    final keys = overrides.keys.where((k) {
      if (_search.isEmpty) return true;
      final entry = overrides.schema[k];
      final label = entry?.label.toLowerCase() ?? k;
      return label.contains(_search) || k.contains(_search);
    }).toList();

    if (keys.isEmpty) {
      return Center(
        child: Text(
          'No matches for "$_search"',
          style: const TextStyle(color: Colors.white54),
        ),
      );
    }

    return ListView.separated(
      controller: scrollController,
      padding: const EdgeInsets.symmetric(vertical: 8),
      itemCount: keys.length,
      separatorBuilder: (_, __) =>
          const Divider(color: Color(0xFF22222D), height: 1),
      itemBuilder: (context, index) {
        final key = keys[index];
        final entry = overrides.schema[key];
        if (entry == null) return const SizedBox.shrink();
        return _buildRow(key, entry, overrides);
      },
    );
  }

  Widget _buildRow(
    String key,
    ThreadLlmOverrideSchemaEntry entry,
    ThreadLlmOverrides overrides,
  ) {
    final effective = overrides.effectiveValue(key);
    final isOverridden = overrides.overrides.containsKey(key);
    final displayValue = isOverridden ? overrides.overrides[key] : effective;
    final type = entry.type;

    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 12, 12, 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        entry.label,
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 14,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ),
                    if (isOverridden)
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 6,
                          vertical: 2,
                        ),
                        decoration: BoxDecoration(
                          color: const Color(
                            0xFF8B5CF6,
                          ).withValues(alpha: 0.15),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: const Text(
                          'override',
                          style: TextStyle(
                            color: Color(0xFF8B5CF6),
                            fontSize: 10,
                          ),
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 2),
                Text(
                  key,
                  style: const TextStyle(color: Colors.white38, fontSize: 11),
                ),
                const SizedBox(height: 6),
                if (type == 'boolean')
                  Row(
                    children: [
                      Switch.adaptive(
                        value: displayValue == true,
                        activeColor: const Color(0xFF8B5CF6),
                        onChanged: _isSaving
                            ? null
                            : (v) => _setOverride(key, v),
                      ),
                      const SizedBox(width: 4),
                      Text(
                        displayValue == true ? 'On' : 'Off',
                        style: const TextStyle(
                          color: Colors.white70,
                          fontSize: 12,
                        ),
                      ),
                      const Spacer(),
                      if (isOverridden)
                        TextButton(
                          onPressed: _isSaving ? null : () => _clearOne(key),
                          child: const Text('Reset to default'),
                        ),
                    ],
                  )
                else
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        child: type == 'number'
                            ? _NumberField(
                                keyName: key,
                                initial: displayValue,
                                isOverridden: isOverridden,
                                isSaving: _isSaving,
                                onSubmit: (v) => _setOverride(key, v),
                                onReset: isOverridden
                                    ? () => _clearOne(key)
                                    : null,
                              )
                            : _StringField(
                                keyName: key,
                                initial: displayValue?.toString() ?? '',
                                isOverridden: isOverridden,
                                isSaving: _isSaving,
                                multiline:
                                    key == 'system_prompt' ||
                                    key == 'api_key' ||
                                    key == 'tts_api_key' ||
                                    key == 'vision_api_key',
                                onSubmit: (v) {
                                  if (v.isEmpty) {
                                    _clearOne(key);
                                  } else {
                                    _setOverride(key, v);
                                  }
                                },
                                onReset: isOverridden
                                    ? () => _clearOne(key)
                                    : null,
                              ),
                      ),
                    ],
                  ),
                if (!isOverridden && effective != null && effective != '')
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text(
                      'Default: ${_formatDefault(effective, type)}',
                      style: const TextStyle(
                        color: Colors.white38,
                        fontSize: 11,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  static String _formatDefault(Object value, String type) {
    if (type == 'number') {
      if (value is num) {
        return value.toString();
      }
    }
    final str = value.toString();
    if (str.length > 80) {
      return '${str.substring(0, 77)}…';
    }
    return str;
  }
}

class _NumberField extends StatefulWidget {
  final String keyName;
  final Object? initial;
  final bool isOverridden;
  final bool isSaving;
  final ValueChanged<Object?> onSubmit;
  final VoidCallback? onReset;

  const _NumberField({
    required this.keyName,
    required this.initial,
    required this.isOverridden,
    required this.isSaving,
    required this.onSubmit,
    this.onReset,
  });

  @override
  State<_NumberField> createState() => _NumberFieldState();
}

class _NumberFieldState extends State<_NumberField> {
  late final TextEditingController _controller;
  late final FocusNode _focusNode;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initial?.toString() ?? '');
    _focusNode = FocusNode();
  }

  @override
  void didUpdateWidget(covariant _NumberField oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!_focusNode.hasFocus && widget.initial != oldWidget.initial) {
      _controller.text = widget.initial?.toString() ?? '';
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  void _commit() {
    if (widget.isSaving) return;
    final raw = _controller.text.trim();
    if (raw.isEmpty) {
      widget.onSubmit(null);
      return;
    }
    if (raw.contains('.')) {
      widget.onSubmit(double.tryParse(raw));
    } else {
      widget.onSubmit(int.tryParse(raw));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: TextField(
            controller: _controller,
            focusNode: _focusNode,
            keyboardType: const TextInputType.numberWithOptions(
              signed: true,
              decimal: true,
            ),
            style: const TextStyle(color: Colors.white, fontSize: 13),
            onSubmitted: (_) => _commit(),
            onEditingComplete: _commit,
            onTapOutside: (_) => _commit(),
            decoration: InputDecoration(
              isDense: true,
              filled: true,
              fillColor: const Color(0xFF1E1E2A),
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 10,
                vertical: 8,
              ),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(8),
                borderSide: BorderSide.none,
              ),
            ),
          ),
        ),
        const SizedBox(width: 6),
        IconButton(
          tooltip: 'Save',
          icon: const Icon(Icons.check, color: Color(0xFF8B5CF6), size: 18),
          onPressed: widget.isSaving ? null : _commit,
        ),
        if (widget.onReset != null)
          IconButton(
            tooltip: 'Reset to default',
            icon: const Icon(Icons.undo, color: Colors.white54, size: 18),
            onPressed: widget.isSaving ? null : widget.onReset,
          ),
      ],
    );
  }
}

class _StringField extends StatefulWidget {
  final String keyName;
  final String initial;
  final bool isOverridden;
  final bool isSaving;
  final bool multiline;
  final ValueChanged<String> onSubmit;
  final VoidCallback? onReset;

  const _StringField({
    required this.keyName,
    required this.initial,
    required this.isOverridden,
    required this.isSaving,
    required this.multiline,
    required this.onSubmit,
    this.onReset,
  });

  @override
  State<_StringField> createState() => _StringFieldState();
}

class _StringFieldState extends State<_StringField> {
  late final TextEditingController _controller;
  late final FocusNode _focusNode;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initial);
    _focusNode = FocusNode();
  }

  @override
  void didUpdateWidget(covariant _StringField oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!_focusNode.hasFocus && widget.initial != oldWidget.initial) {
      _controller.text = widget.initial;
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  void _commit() {
    if (widget.isSaving) return;
    widget.onSubmit(_controller.text.trim());
  }

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(
          child: TextField(
            controller: _controller,
            focusNode: _focusNode,
            minLines: widget.multiline ? 3 : 1,
            maxLines: widget.keyName == 'system_prompt'
                ? 8
                : (widget.multiline ? 3 : 1),
            style: const TextStyle(color: Colors.white, fontSize: 13),
            onSubmitted: (_) => _commit(),
            onEditingComplete: _commit,
            onTapOutside: (_) => _commit(),
            decoration: InputDecoration(
              isDense: true,
              filled: true,
              fillColor: const Color(0xFF1E1E2A),
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 10,
                vertical: 8,
              ),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(8),
                borderSide: BorderSide.none,
              ),
            ),
          ),
        ),
        const SizedBox(width: 6),
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Row(
            children: [
              IconButton(
                tooltip: 'Save',
                icon: const Icon(
                  Icons.check,
                  color: Color(0xFF8B5CF6),
                  size: 18,
                ),
                onPressed: widget.isSaving ? null : _commit,
              ),
              if (widget.onReset != null)
                IconButton(
                  tooltip: 'Reset to default',
                  icon: const Icon(Icons.undo, color: Colors.white54, size: 18),
                  onPressed: widget.isSaving ? null : widget.onReset,
                ),
            ],
          ),
        ),
      ],
    );
  }
}
