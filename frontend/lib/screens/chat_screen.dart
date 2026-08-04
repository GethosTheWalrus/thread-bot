import 'dart:async';
import 'dart:convert';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:threadbot/models/message.dart';
import 'package:threadbot/models/thread.dart';
import 'package:threadbot/services/api_service.dart';
import 'package:threadbot/services/autonomy_api.dart';
import 'package:threadbot/models/autonomy.dart';
import 'package:threadbot/widgets/chat_message_list.dart';
import 'package:threadbot/widgets/threadbot_avatar.dart';
import 'package:threadbot/widgets/chat_input.dart';
import 'package:threadbot/widgets/sidebar.dart';
import 'package:threadbot/widgets/thread_participant_manager.dart';

class ChatScreen extends StatefulWidget {
  final String? initialThreadId;
  final VoidCallback? onUnauthorized;
  const ChatScreen({super.key, this.initialThreadId, this.onUnauthorized});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _AgentSetupSheet extends StatefulWidget {
  @override
  State<_AgentSetupSheet> createState() => _AgentSetupSheetState();
}

class _AgentSetupSheetState extends State<_AgentSetupSheet> {
  final _name = TextEditingController(text: 'My Agent');
  final _instructions = TextEditingController(
    text: 'Be helpful, precise, and explain your reasoning clearly.',
  );
  String? _error;

  @override
  void dispose() {
    _name.dispose();
    _instructions.dispose();
    super.dispose();
  }

  void _submit() {
    final name = _name.text.trim();
    final prompt = _instructions.text.trim();
    if (name.isEmpty) {
      setState(() => _error = 'Give your agent a name.');
      return;
    }
    if (prompt.isEmpty) {
      setState(
        () => _error = 'Add a few instructions so the agent knows how to help.',
      );
      return;
    }
    Navigator.pop(context, {'name': name, 'prompt': prompt});
  }

  @override
  Widget build(BuildContext context) {
    final bottom = MediaQuery.viewInsetsOf(context).bottom;
    final availableHeight = MediaQuery.sizeOf(context).height - bottom - 32;
    return SafeArea(
      child: Padding(
        padding: EdgeInsets.fromLTRB(24, 12, 24, 20 + bottom),
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxHeight: availableHeight.clamp(320.0, 720.0),
          ),
          child: SingleChildScrollView(
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
                const SizedBox(height: 24),
                const Text(
                  'Create an Agent Thread',
                  style: TextStyle(fontSize: 23, fontWeight: FontWeight.w700),
                ),
                const SizedBox(height: 8),
                Text(
                  'Give a focused assistant a durable identity. Your existing thread context will be included when it runs.',
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: .62),
                    height: 1.45,
                  ),
                ),
                const SizedBox(height: 24),
                TextField(
                  controller: _name,
                  textInputAction: TextInputAction.next,
                  decoration: const InputDecoration(
                    labelText: 'Agent name',
                    hintText: 'e.g. Research partner',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 18),
                TextField(
                  controller: _instructions,
                  minLines: 5,
                  maxLines: 10,
                  decoration: const InputDecoration(
                    labelText: 'Instructions',
                    hintText:
                        'What should this agent do, and how should it respond?',
                    alignLabelWithHint: true,
                    border: OutlineInputBorder(),
                  ),
                ),
                if (_error != null) ...[
                  const SizedBox(height: 10),
                  Text(_error!, style: TextStyle(color: Color(0xFFFCA5A5))),
                ],
                const SizedBox(height: 24),
                FilledButton.icon(
                  onPressed: _submit,
                  icon: const Icon(Icons.auto_awesome),
                  label: const Padding(
                    padding: EdgeInsets.symmetric(vertical: 13),
                    child: Text('Create agent'),
                  ),
                ),
                const SizedBox(height: 8),
                TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('Not now'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _ChatScreenState extends State<ChatScreen> with TickerProviderStateMixin {
  late final ApiService _api;
  final ScrollController _scrollController = ScrollController();
  // No GlobalKey needed — use Builder + Scaffold.of() for drawer access

  // State
  List<ThreadListItem> _threads = [];
  String? _activeThreadId;
  String _activeThreadMode = 'chat';
  List<Message> _messages = [];
  bool _isLoadingThreads = false;
  bool _isLoadingMessages = false;
  bool _isSending = false;
  bool _isCreatingAgent = false;
  bool _isChangingThreadMode = false;
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
  Timer? _broadcastRetry;
  int _broadcastAttempt = 0;
  bool _disposed = false;
  bool _continuePromptOpen = false;

  // Animation
  late final AutonomyApiService _autonomyApi;
  Agent? _agent;
  ThreadAgentSummary? _threadAgentSummary;
  List<ThreadAgentSummary> _participants = const [];
  final Map<String, ThreadRunSummary> _activeRunSummaries = {};
  int _pendingApprovals = 0;
  final Map<String, Run> _activeRuns = {};
  final Map<String, List<RunEvent>> _runEvents = {};
  final Map<String, int> _runCursors = {};
  final Map<String, int> _runPollFailures = {};
  final Map<String, DateTime> _runRetryAt = {};
  Timer? _runPollTimer;
  final Set<String> _runPollInFlight = {};
  int _runGeneration = 0;

  @override
  void initState() {
    super.initState();

    _api = ApiService(onUnauthorized: widget.onUnauthorized);
    _autonomyApi = AutonomyApiService(onUnauthorized: widget.onUnauthorized);

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
    if (kIsWeb) _subscribeToBroadcast();
  }

  void _subscribeToBroadcast() {
    if (_disposed) return;
    _broadcastRetry?.cancel();
    _broadcastChannel?.sink.close();
    _broadcastChannel = _api.subscribeBroadcast();
    _broadcastChannel?.stream.listen(
      (data) {
        if (_disposed) return;
        final event = jsonDecode(data as String) as Map<String, dynamic>;
        _broadcastAttempt = 0;
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
      onDone: () {
        _scheduleBroadcastReconnect();
      },
    );
  }

  void _scheduleBroadcastReconnect() {
    if (_disposed || _broadcastRetry?.isActive == true) return;
    final delay = Duration(
      milliseconds: 250 * (1 << _broadcastAttempt.clamp(0, 6)),
    );
    _broadcastAttempt++;
    _broadcastRetry = Timer(delay, _subscribeToBroadcast);
  }

  @override
  void dispose() {
    _disposed = true;
    _resetRunTracking();
    _broadcastChannel?.sink.close();
    _broadcastRetry?.cancel();
    _runPollTimer?.cancel();
    _threadRefreshTimer?.cancel();
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
      if (mounted) {
        setState(() => _isAtBottom = atBottom);
      } else {
        _isAtBottom = atBottom;
      }
    }
  }

  // ── Data Loading ──────────────────────────────────────────────────

  Future<void> _loadThreads({bool silent = false}) async {
    if (!silent) setState(() => _isLoadingThreads = true);
    try {
      final threads = await _api.getThreads();
      if (mounted) {
        setState(() {
          _threads = {
            for (final thread in threads) thread.id: thread,
          }.values.toList();
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
    final switchingThread = _activeThreadId != threadId;
    _runPollTimer?.cancel();
    final knownThread = _threads.where((t) => t.id == threadId).firstOrNull;
    setState(() {
      _isLoadingMessages = true;
      _activeThreadId = threadId;
      // Preserve the displayed mode and agent while the request is in flight.
      // In particular, do not briefly turn a generating agent thread into chat.
      if (switchingThread) _resetRunTracking();
      _isSending = knownThread?.isGenerating == true;
      _error = null;
      _hasToolOverrides = false;
      _hasLlmOverrides = false;
      if (switchingThread) _isAtBottom = true;
    });
    try {
      SystemNavigator.routeInformationUpdated(
        uri: Uri.parse('/thread/$threadId'),
      );
      final thread = await _api.getThread(threadId);
      if (mounted && _activeThreadId == threadId) {
        setState(() {
          _messages = thread.messages;
          _activeThreadMode = thread.mode;
          if (thread.mode != 'agent') _agent = null;
          _threadAgentSummary = thread.agent;
          _participants = thread.agents;
          _pendingApprovals = thread.pendingApprovals;
          _activeRunSummaries
            ..clear()
            ..addEntries(thread.activeRuns.map((run) => MapEntry(run.id, run)));
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
          _isSending = thread.isGenerating;
        });
        _reconcileRunSummaries(thread.activeRuns, thread.id);
        _scrollToBottom(force: true, jump: true, settleLayout: true);
        if (thread.agents.isEmpty) {
          try {
            final roster = await _api.getThreadAgents(threadId);
            if (mounted && _activeThreadId == threadId) {
              setState(() => _participants = roster);
            }
          } catch (_) {}
        }
        await _loadAgentForThread(thread);
        if (!mounted || _activeThreadId != threadId) return;

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
      if (mounted && _activeThreadId == threadId)
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
      if (mounted && _activeThreadId == threadId) {
        setState(
          () => _hasToolOverrides = overrides.any((o) => o['enabled'] == false),
        );
      }
    } catch (_) {
      // Non-critical — don't show error
    }
  }

  Future<void> _loadAgentForThread(Thread thread) async {
    if (thread.mode != 'agent' || thread.agent == null) {
      if (mounted && _activeThreadId == thread.id) {
        setState(() => _agent = null);
      }
      return;
    }
    try {
      final summary = thread.agent!;
      final agent = await _autonomyApi.agent(summary.id);
      if (!mounted || _activeThreadId != thread.id) return;
      setState(() => _agent = agent);
      final runs = await _autonomyApi.runs(agent.id);
      final active = runs.items.where(
        (run) => run.threadId == thread.id && !_isTerminalRun(run.status),
      );
      if (mounted && _activeThreadId == thread.id) {
        for (final run in active) _upsertRun(run);
        _startRunStatus();
      }
    } catch (_) {
      // Keep the nested thread summary and any known agent. A failed detail
      // request must not make a genuine agent thread look like chat.
    }
  }

  void _resetRunTracking() {
    _runGeneration++;
    _runPollTimer?.cancel();
    _activeRuns.clear();
    _runEvents.clear();
    _runCursors.clear();
    _runPollFailures.clear();
    _runRetryAt.clear();
    _runPollInFlight.clear();
  }

  void _upsertRun(Run run) {
    if (run.id.isEmpty || _isTerminalRun(run.status)) return;
    _activeRuns[run.id] = run;
    _runEvents.putIfAbsent(run.id, () => <RunEvent>[]);
    _runCursors.putIfAbsent(run.id, () => 0);
  }

  void _reconcileRunSummaries(
    List<ThreadRunSummary> summaries,
    String threadId,
  ) {
    final ids = summaries.map((r) => r.id).where((id) => id.isNotEmpty).toSet();
    setState(() {
      for (final summary in summaries) {
        if (!_isTerminalRun(summary.status)) {
          _upsertRun(
            Run(
              id: summary.id,
              agentId: summary.agentId ?? '',
              threadId: threadId,
              status: summary.status,
              mode: summary.mode,
              agentName: summary.agentName,
              agentHandle: summary.agentHandle,
              outputSummary: summary.outputSummary,
            ),
          );
        }
      }
      for (final id in _activeRuns.keys.toList()) {
        if (!ids.contains(id)) _removeRun(id);
      }
      if (_activeRuns.isNotEmpty) _isSending = true;
    });
    for (final summary in summaries) {
      if (!_isTerminalRun(summary.status)) {
        _loadRunDetail(summary.id, _runGeneration);
      }
    }
    if (_activeRuns.isNotEmpty) _startRunStatus();
  }

  Future<void> _loadRunDetail(String runId, int generation) async {
    try {
      final run = await _autonomyApi.runDetail(runId);
      if (!mounted ||
          generation != _runGeneration ||
          _activeThreadId != run.threadId)
        return;
      if (_isTerminalRun(run.status)) {
        setState(() => _removeRun(runId));
      } else {
        setState(() => _upsertRun(run));
      }
    } catch (_) {}
  }

  void _removeRun(String runId) {
    _activeRuns.remove(runId);
    _runEvents.remove(runId);
    _runCursors.remove(runId);
    _runPollFailures.remove(runId);
    _runRetryAt.remove(runId);
    _runPollInFlight.remove(runId);
    if (_activeRuns.isEmpty && mounted) _isSending = false;
  }

  Future<void> _loadLlmOverrideStatus(String threadId) async {
    try {
      final overrides = await _api.getThreadLlmOverrides(threadId);
      if (mounted && _activeThreadId == threadId) {
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

  void _showThreadControls() {
    final threadId = _activeThreadId;
    final thread = _threads.where((item) => item.id == threadId).firstOrNull;
    final sheetHeight = MediaQuery.sizeOf(context).height * .94;
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xFF16161E),
      constraints: BoxConstraints(maxWidth: 780, maxHeight: sheetHeight),
      clipBehavior: Clip.antiAlias,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) => _ThreadControlsSheet(
        threadId: threadId,
        api: _api,
        estimatedTokens: _contextEstimatedTokens,
        contextWindow: _contextWindow,
        hasLlmOverrides: _hasLlmOverrides,
        hasToolOverrides: _hasToolOverrides,
        initialOverrides: threadId == null ? _pendingToolOverrides : null,
        onToolChanged: (hasOverrides) {
          if (threadId != null && _activeThreadId == threadId) {
            setState(() => _hasToolOverrides = hasOverrides);
            _loadToolOverrideStatus(threadId);
          }
        },
        onPendingToolsChanged: (overrides) {
          if (threadId == null && mounted) {
            setState(() {
              _pendingToolOverrides = overrides;
              _hasToolOverrides = overrides.any((o) => o['enabled'] == false);
            });
          }
        },
        onLlmChanged: threadId == null
            ? null
            : (hasOverrides) {
                if (_activeThreadId == threadId) {
                  setState(() => _hasLlmOverrides = hasOverrides);
                  _loadLlmOverrideStatus(threadId);
                }
              },
        threadMode: _activeThreadMode,
        modeChangeBusy:
            _isSending ||
            _activeRuns.isNotEmpty ||
            _isChangingThreadMode ||
            _isCreatingAgent,
        participants: _participants,
        turnLimit: thread?.agentTurnLimit ?? 0,
        activeRunCount: _activeRunSummaries.length,
        pendingApprovals: _pendingApprovals,
        onModeChanged: threadId == null ? null : _changeThreadMode,
        onParticipantsChanged: threadId == null
            ? null
            : () {
                _loadThread(threadId);
                _loadThreads(silent: true);
              },
        onOpenAgent: (agentId) =>
            Navigator.pushNamed(context, '/agent-details/$agentId'),
        onOpenAllAgents: () => Navigator.pushNamed(context, '/agents-list'),
        onOpenWorkspaceSettings: _openSettings,
        onOpenMcp: _openMCP,
        onOpenSkills: _openSkills,
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

    if (_agent != null && _activeThreadId != null) {
      try {
        setState(
          () => _upsertRun(
            Run(
              id: 'starting-${DateTime.now().microsecondsSinceEpoch}',
              threadId: _activeThreadId!,
              status: 'starting',
              agentId: _agent!.id,
              agentName: _agent!.name,
              agentHandle: _agent!.handle,
            ),
          ),
        );
        final run = await _autonomyApi.runThread(
          _activeThreadId!,
          AgentRunRequest(message: content),
          idempotencyKey: AutonomyApiService.newIdempotencyKey(),
        );
        if (mounted) {
          setState(() {
            _activeRuns.removeWhere((id, _) => id.startsWith('starting-'));
            _upsertRun(run);
          });
          _startRunStatus();
        }
      } catch (e) {
        if (mounted) {
          setState(() {
            _messages.removeWhere((m) => m.id == optimisticMsg.id);
            _resetRunTracking();
            _isSending = false;
          });
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(SnackBar(content: Text('Agent run failed: $e')));
        }
      }
      return;
    }

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

  void _startRunStatus() {
    if (_runPollTimer?.isActive == true || _activeRuns.isEmpty) return;
    _runPollTimer = Timer.periodic(
      const Duration(seconds: 3),
      (_) => _pollRuns(),
    );
  }

  Future<void> _pollRuns() async {
    if (_disposed || _runPollInFlight.length >= _activeRuns.length) return;
    final generation = _runGeneration;
    final snapshot = _activeRuns.values.toList();
    await Future.wait(snapshot.map((run) => _pollRun(run, generation)));
    if (_activeRuns.isEmpty) _runPollTimer?.cancel();
  }

  Future<void> _pollRun(Run run, int generation) async {
    if (_runPollInFlight.contains(run.id) ||
        (_runRetryAt[run.id]?.isAfter(DateTime.now()) ?? false))
      return;
    _runPollInFlight.add(run.id);
    try {
      final page = await _autonomyApi.events(
        run.id,
        after: _runCursors[run.id] ?? 0,
      );
      if (!mounted ||
          generation != _runGeneration ||
          !_activeRuns.containsKey(run.id))
        return;
      if (page.items.isNotEmpty) {
        setState(() {
          final events = _runEvents.putIfAbsent(run.id, () => <RunEvent>[]);
          final known = events.map((event) => event.sequence).toSet();
          events.addAll(page.items.where((event) => known.add(event.sequence)));
          _runCursors[run.id] = events.isEmpty ? 0 : events.last.sequence;
        });
      }
      final latest = await _autonomyApi.runDetail(run.id);
      if (!mounted ||
          generation != _runGeneration ||
          !_activeRuns.containsKey(run.id))
        return;
      if (_isTerminalRun(latest.status)) {
        await _reloadThreadSilently();
        if (mounted && generation == _runGeneration)
          setState(() => _removeRun(run.id));
      } else {
        setState(() => _activeRuns[run.id] = latest);
      }
      _runPollFailures[run.id] = 0;
      _runRetryAt.remove(run.id);
    } catch (e) {
      final failures = (_runPollFailures[run.id] ?? 0) + 1;
      _runPollFailures[run.id] = failures;
      _runRetryAt[run.id] = DateTime.now().add(
        Duration(seconds: 1 << (failures.clamp(1, 5) - 1)),
      );
      if (mounted && failures == 3) {
        _showAgentError(
          'Run status is temporarily unavailable. Retrying with backoff; the run is still active.',
        );
      }
    } finally {
      _runPollInFlight.remove(run.id);
    }
  }

  bool _isTerminalRun(String status) => const {
    'completed',
    'succeeded',
    'failed',
    'cancelled',
    'canceled',
    'rejected',
    'exhausted',
    'timed_out',
    'suppressed',
    'dead_lettered',
    'outcome_unknown',
  }.contains(status.toLowerCase());

  List<Widget> _buildRunChips() {
    if (_activeRuns.isEmpty) return const [];
    final runs = _activeRuns.values.toList()
      ..sort((a, b) {
        final left = a.queuedAt ?? DateTime.fromMillisecondsSinceEpoch(0);
        final right = b.queuedAt ?? DateTime.fromMillisecondsSinceEpoch(0);
        return left.compareTo(right);
      });
    return runs.map(_buildRunChip).toList();
  }

  Widget _buildRunChip(Run run) {
    final events = _runEvents[run.id] ?? const <RunEvent>[];
    final latest = events.isEmpty ? null : events.last;
    final waiting = run.status.toLowerCase() == 'waiting_approval';
    final identity = [
      if (run.agentName?.isNotEmpty == true) run.agentName,
      if (run.agentHandle?.isNotEmpty == true) '@${run.agentHandle}',
    ].join(' ');
    final output = _compactMarkdown(
      run.outputSummary ?? _safeEventText(latest),
    );
    final statusColor = waiting
        ? const Color(0xFFFBBF24)
        : const Color(0xFF8B5CF6);
    return Container(
      margin: const EdgeInsets.fromLTRB(16, 0, 16, 8),
      child: Tooltip(
        message: 'Open ${identity.isEmpty ? 'agent' : identity} run details',
        child: Semantics(
          button: true,
          label: '${identity.isEmpty ? 'Agent' : identity} run, ${run.status}',
          child: Material(
            color: const Color(0xFF1A1527),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
              side: BorderSide(color: statusColor.withValues(alpha: 0.35)),
            ),
            child: InkWell(
              borderRadius: BorderRadius.circular(16),
              onTap: () =>
                  Navigator.pushNamed(context, '/agent-runs/${run.id}'),
              child: Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: 14,
                  vertical: 10,
                ),
                child: Row(
                  children: [
                    Icon(
                      waiting
                          ? Icons.hourglass_top_rounded
                          : Icons.autorenew_rounded,
                      size: 16,
                      color: waiting ? const Color(0xFFFBBF24) : statusColor,
                    ),
                    const SizedBox(width: 8),
                    Flexible(
                      child: Text(
                        '${identity.isEmpty ? 'Agent' : identity} · ${run.status.replaceAll('_', ' ')}${run.route.isEmpty ? '' : ' · ${run.route.replaceAll('_', ' ')}'}',
                        style: const TextStyle(
                          fontSize: 12,
                          color: Color(0xFFE9D5FF),
                          fontWeight: FontWeight.w500,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    if (output?.isNotEmpty == true) ...[
                      const SizedBox(width: 6),
                      Flexible(
                        child: Text(
                          output!,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 11,
                            color: Colors.white54,
                          ),
                        ),
                      ),
                    ],
                    const SizedBox(width: 4),
                    Icon(
                      Icons.chevron_right_rounded,
                      size: 18,
                      color: Colors.white.withValues(alpha: 0.3),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  String? _safeEventText(RunEvent? event) {
    if (event == null) return null;
    final value =
        event.payload['display_content'] ??
        event.payload['content'] ??
        event.payload['message'] ??
        event.payload['error'];
    return value is String ? value : null;
  }

  String? _compactMarkdown(String? value) {
    if (value == null || value.trim().isEmpty) return null;
    return value
        .replaceAll(RegExp(r'```[\s\S]*?```'), ' code ')
        .replaceAll(RegExp(r'[`*_>#\[\]]'), '')
        .replaceAll(RegExp(r'\s+'), ' ')
        .trim();
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
      _agent = null;
      _resetRunTracking();
      _isSending = false;
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
                icon: Icons.smart_toy_outlined,
                title: 'Agent Thread',
                subtitle:
                    'A configured agent conversation with runs and actions',
                badgeText: 'A',
                onTap: () => Navigator.pop(context, 'agent'),
              ),
              const SizedBox(height: 10),
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

    if (choice == 'agent') {
      await _startAgentNewChat();
    } else if (choice == 'discord') {
      await _startDiscordNewChat();
    } else if (choice == 'regular') {
      await _startRegularNewChat();
    }
  }

  Future<void> _startAgentNewChat() async {
    if (_isCreatingAgent) return;
    setState(() => _isCreatingAgent = true);
    final result = await _showAgentSetupSheet();
    if (result == null) {
      if (mounted) setState(() => _isCreatingAgent = false);
      return;
    }
    try {
      final agent = await _autonomyApi.createAgent({
        'name': result['name'],
        'description': result['prompt'],
        'execution_mode': 'act',
      });
      // Establish the new thread before touching its draft. If setup fails,
      // the user is still left on the correct thread with agent controls.
      await _loadThread(agent.threadId);
      if (!mounted) return;
      if (_activeThreadId == agent.threadId && _agent == null) {
        setState(() {
          _agent = agent;
          _activeThreadMode = 'agent';
          _threadAgentSummary = ThreadAgentSummary(
            id: agent.id,
            name: agent.name,
            status: agent.status,
            executionMode: agent.executionMode,
            activeVersionId: agent.activeVersionId,
          );
        });
      }
      await _initializeAgent(agent.id, result['prompt']!);
      await _loadThread(agent.threadId);
      _loadThreads();
    } catch (e) {
      if (mounted)
        _showAgentError(
          'Agent thread created, but setup is incomplete. Open Agent controls to finish it. ($e)',
          action: 'Agent controls',
        );
    } finally {
      if (mounted) setState(() => _isCreatingAgent = false);
    }
  }

  Future<Map<String, String>?> _showAgentSetupSheet() async {
    return showModalBottomSheet<Map<String, String>>(
      context: context,
      isScrollControlled: true,
      backgroundColor: const Color(0xFF16161E),
      constraints: const BoxConstraints(maxWidth: 680),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (ctx) => _AgentSetupSheet(),
    );
  }

  Future<void> _initializeAgent(String agentId, String instructions) async {
    Draft draft;
    try {
      draft = await _autonomyApi.draft(agentId);
    } on ApiException catch (error) {
      if (error.status != 404) rethrow;
      draft = Draft(agentId: agentId);
    }
    await _autonomyApi.saveDraft(agentId, {
      'optimistic_lock_version': draft.optimisticLockVersion,
      'schema_version': draft.schemaVersion,
      'config': draft.config,
      'prompt_template': instructions,
      'tool_selection': draft.toolSelection,
      'skill_selection': draft.skillSelection,
      'credential_bindings': draft.credentialBindings,
    });
    await _autonomyApi.activate(agentId);
  }

  void _showAgentError(String message, {String? action}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: Colors.red.shade800,
        action: action == null
            ? null
            : SnackBarAction(label: action, onPressed: _showThreadControls),
      ),
    );
  }

  Future<void> _changeThreadMode(String mode) async {
    final id = _activeThreadId;
    if (id == null ||
        mode == _activeThreadMode ||
        _isSending ||
        _activeRuns.isNotEmpty ||
        _isChangingThreadMode)
      return;
    final target = mode == 'agent' ? 'Agent Thread' : 'Chat Thread';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Switch to $target?'),
        content: Text(
          mode == 'agent'
              ? 'This keeps the conversation history and uses an agent for future messages.'
              : 'The agent, its configuration, and history stay attached. Only this composer switches back to normal chat.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Switch'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _isChangingThreadMode = true);
    try {
      final needsSetup = _threadAgentSummary?.activeVersionId == null;
      Map<String, String>? setup;
      if (mode == 'agent' && needsSetup) {
        setup = await _showAgentSetupSheet();
        if (setup == null) return;
      }
      final updated = await _api.setThreadMode(
        id,
        mode: mode,
        agentName: setup?['name'],
      );
      await _loadThread(id);
      if (!mounted || _activeThreadId != id) return;
      if (mode == 'agent' &&
          updated.agent != null &&
          updated.agent!.activeVersionId == null &&
          setup != null) {
        await _initializeAgent(updated.agent!.id, setup['prompt']!);
        await _loadThread(id);
      }
      if (mounted && _activeThreadId == id) {
        setState(() => _activeThreadMode = updated.mode);
      }
      await _loadThreads(silent: true);
    } catch (e) {
      if (mounted) _showAgentError('Could not switch thread mode: $e');
    } finally {
      if (mounted) setState(() => _isChangingThreadMode = false);
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
          _agent = null;
          _resetRunTracking();
          _isSending = false;
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
        _agent = null;
        _resetRunTracking();
        _isSending = false;
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

  Future<void> _setThreadPinned(String threadId, bool isPinned) async {
    final index = _threads.indexWhere((thread) => thread.id == threadId);
    if (index == -1) return;
    final previous = _threads[index].isPinned;

    setState(() => _threads[index].isPinned = isPinned);
    try {
      await _api.setThreadPinned(threadId, isPinned);
      _loadThreads(silent: true);
    } catch (e) {
      if (mounted) {
        final currentIndex = _threads.indexWhere(
          (thread) => thread.id == threadId,
        );
        if (currentIndex != -1) {
          setState(() => _threads[currentIndex].isPinned = previous);
        }
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Pin update failed: $e')));
      }
    }
  }

  void _scrollToBottom({
    bool force = false,
    bool jump = false,
    bool settleLayout = false,
  }) {
    if (!force && !_isAtBottom) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) return;
      final target = _scrollController.position.maxScrollExtent;
      if (jump) {
        _scrollController.jumpTo(target);
      } else {
        _scrollController.animateTo(
          target,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
      if (!_isAtBottom && mounted) setState(() => _isAtBottom = true);
      if (settleLayout) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (!mounted || !_scrollController.hasClients || !_isAtBottom) return;
          _scrollController.jumpTo(_scrollController.position.maxScrollExtent);
        });
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
      body: Stack(
        children: [
          Row(
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
                  onPin: _setThreadPinned,
                  onDeleteAll: _deleteAllThreads,
                  onMCP: _openMCP,
                  onSkills: _openSkills,
                  onSettings: _openSettings,
                  onAgents: () => Navigator.pushNamed(context, '/agents-list'),
                ),

              // Main chat area
              Expanded(
                child: Column(
                  children: [
                    _buildTopBar(isWide),
                    Expanded(child: _buildChatArea()),
                    ChatInput(
                      onSend: _sendMessage,
                      isSending: _isSending,
                      onThreadControlsPressed: _showThreadControls,
                      hasToolOverrides: _hasToolOverrides,
                      hasLlmOverrides: _hasLlmOverrides,
                      estimatedTokens: _contextEstimatedTokens,
                      contextWindow: _contextWindow,
                      participants: _participants,
                    ),
                  ],
                ),
              ),
            ],
          ),
          if (_isCreatingAgent)
            Positioned.fill(
              child: ColoredBox(
                color: Color(0x990D0D12),
                child: Center(
                  child: Card(
                    color: Color(0xFF242432),
                    child: Padding(
                      padding: EdgeInsets.all(24),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          CircularProgressIndicator(),
                          SizedBox(height: 14),
                          Text('Creating agent thread…'),
                        ],
                      ),
                    ),
                  ),
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
                  onPin: _setThreadPinned,
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
                  onAgents: () {
                    Navigator.pop(context);
                    Navigator.pushNamed(context, '/agents-list');
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

    return Stack(
      children: [
        Positioned.fill(
          child: ChatMessageList(
            messages: _messages,
            scrollController: _scrollController,
            isSending: _isSending,
            footerWidgets: _buildRunChips(),
          ),
        ),
        if (!_isAtBottom)
          Positioned(
            right: 18,
            bottom: 14,
            child: Semantics(
              button: true,
              label: 'Scroll to latest message',
              child: Tooltip(
                message: 'Scroll to latest message',
                child: FloatingActionButton.small(
                  heroTag: null,
                  onPressed: () => _scrollToBottom(force: true),
                  backgroundColor: const Color(0xFF272336),
                  foregroundColor: const Color(0xFFE9D5FF),
                  elevation: 5,
                  child: const Icon(Icons.arrow_downward_rounded, size: 20),
                ),
              ),
            ),
          ),
      ],
    );
  }

  Widget _buildWelcomeScreen() {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Glowing 3D Poly-Bot Avatar
            const ThreadbotAvatar(
              size: 120,
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

class _ThreadControlsSheet extends StatefulWidget {
  final String? threadId;
  final ApiService api;
  final int estimatedTokens;
  final int contextWindow;
  final bool hasLlmOverrides;
  final bool hasToolOverrides;
  final List<Map<String, dynamic>>? initialOverrides;
  final ValueChanged<bool>? onToolChanged;
  final ValueChanged<List<Map<String, dynamic>>>? onPendingToolsChanged;
  final ValueChanged<bool>? onLlmChanged;
  final String threadMode;
  final bool modeChangeBusy;
  final List<ThreadAgentSummary> participants;
  final int turnLimit;
  final int activeRunCount;
  final int pendingApprovals;
  final ValueChanged<String>? onModeChanged;
  final VoidCallback? onParticipantsChanged;
  final ValueChanged<String> onOpenAgent;
  final VoidCallback onOpenAllAgents;
  final VoidCallback onOpenWorkspaceSettings;
  final VoidCallback onOpenMcp;
  final VoidCallback onOpenSkills;

  const _ThreadControlsSheet({
    required this.threadId,
    required this.api,
    required this.estimatedTokens,
    required this.contextWindow,
    required this.hasLlmOverrides,
    required this.hasToolOverrides,
    this.initialOverrides,
    this.onToolChanged,
    this.onPendingToolsChanged,
    this.onLlmChanged,
    required this.threadMode,
    required this.modeChangeBusy,
    required this.participants,
    required this.turnLimit,
    required this.activeRunCount,
    required this.pendingApprovals,
    this.onModeChanged,
    this.onParticipantsChanged,
    required this.onOpenAgent,
    required this.onOpenAllAgents,
    required this.onOpenWorkspaceSettings,
    required this.onOpenMcp,
    required this.onOpenSkills,
  });

  @override
  State<_ThreadControlsSheet> createState() => _ThreadControlsSheetState();
}

class _ThreadControlsSheetState extends State<_ThreadControlsSheet>
    with SingleTickerProviderStateMixin {
  int _tab = 0;
  final Set<int> _visitedTabs = {0};
  late bool _hasLlmOverrides = widget.hasLlmOverrides;
  late bool _hasToolOverrides = widget.hasToolOverrides;
  late final TabController _tabController;

  @override
  void initState() {
    super.initState();
    _tabController = TabController(length: 5, vsync: this);
  }

  @override
  void dispose() {
    _tabController.dispose();
    super.dispose();
  }

  void _selectTab(int tab, {bool animate = true}) {
    if (animate) _tabController.animateTo(tab);
    setState(() {
      _tab = tab;
      _visitedTabs.add(tab);
    });
  }

  void _onLlmChanged(bool value) {
    setState(() => _hasLlmOverrides = value);
    widget.onLlmChanged?.call(value);
  }

  void _onToolChanged(bool value) {
    setState(() => _hasToolOverrides = value);
    widget.onToolChanged?.call(value);
  }

  void _onPendingToolsChanged(List<Map<String, dynamic>> overrides) {
    setState(
      () => _hasToolOverrides = overrides.any((o) => o['enabled'] == false),
    );
    widget.onPendingToolsChanged?.call(overrides);
  }

  void _closeAndRun(VoidCallback action) {
    Navigator.pop(context);
    WidgetsBinding.instance.addPostFrameCallback((_) => action());
  }

  @override
  Widget build(BuildContext context) {
    final screenHeight = MediaQuery.sizeOf(context).height;
    final bottom = MediaQuery.viewInsetsOf(context).bottom;
    final targetHeight = screenHeight * .94;
    final availableHeight = (screenHeight - bottom - 12).clamp(
      180.0,
      double.infinity,
    );
    final height = targetHeight < availableHeight
        ? targetHeight
        : availableHeight;
    return SafeArea(
      child: AnimatedPadding(
        duration: const Duration(milliseconds: 180),
        padding: EdgeInsets.only(bottom: bottom),
        child: Center(
          child: ConstrainedBox(
            constraints: BoxConstraints(
              maxWidth: 780,
              maxHeight: availableHeight,
            ),
            child: SizedBox(
              height: height,
              child: Column(
                children: [
                  const SizedBox(height: 8),
                  Container(
                    width: 28,
                    height: 3,
                    decoration: BoxDecoration(
                      color: Colors.white24,
                      borderRadius: BorderRadius.circular(4),
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 4, 8, 2),
                    child: Row(
                      children: [
                        const Expanded(
                          child: Text(
                            'Thread settings',
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                        ),
                        IconButton(
                          visualDensity: VisualDensity.compact,
                          tooltip: 'Close',
                          onPressed: () => Navigator.pop(context),
                          icon: const Icon(
                            Icons.close_rounded,
                            color: Colors.white70,
                          ),
                        ),
                      ],
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 8),
                    child: LayoutBuilder(
                      builder: (context, constraints) {
                        final compact = constraints.maxWidth < 430;
                        return TabBar(
                          controller: _tabController,
                          onTap: (index) => _selectTab(index, animate: false),
                          isScrollable: true,
                          tabAlignment: TabAlignment.start,
                          labelPadding: EdgeInsets.symmetric(
                            horizontal: compact ? 4 : 12,
                          ),
                          indicatorSize: TabBarIndicatorSize.tab,
                          indicatorWeight: 2,
                          dividerColor: Colors.white10,
                          labelColor: Colors.white,
                          unselectedLabelColor: Colors.white54,
                          tabs: [
                            const Tab(text: 'General'),
                            const Tab(text: 'Agents'),
                            const Tab(text: 'Context'),
                            Tab(
                              child: _TabLabel(
                                text: 'Response',
                                active: _hasLlmOverrides,
                              ),
                            ),
                            Tab(
                              child: _TabLabel(
                                text: 'MCP Tools',
                                active: _hasToolOverrides,
                              ),
                            ),
                          ],
                        );
                      },
                    ),
                  ),
                  const SizedBox(height: 4),
                  Expanded(
                    child: IndexedStack(
                      index: _tab,
                      children: [
                        _GeneralControlsTab(
                          hasThread: widget.threadId != null,
                          threadMode: widget.threadMode,
                          modeChangeBusy: widget.modeChangeBusy,
                          participantCount: widget.participants.length,
                          activeRunCount: widget.activeRunCount,
                          pendingApprovals: widget.pendingApprovals,
                          onModeChanged: widget.onModeChanged == null
                              ? null
                              : (mode) => _closeAndRun(
                                  () => widget.onModeChanged!(mode),
                                ),
                          onOpenAllAgents: () =>
                              _closeAndRun(widget.onOpenAllAgents),
                          onOpenWorkspaceSettings: () =>
                              _closeAndRun(widget.onOpenWorkspaceSettings),
                          onOpenMcp: () => _closeAndRun(widget.onOpenMcp),
                          onOpenSkills: () => _closeAndRun(widget.onOpenSkills),
                        ),
                        widget.threadId == null
                            ? const _UnavailableControlTab(
                                message:
                                    'Send the first message to save this thread before adding agents.',
                              )
                            : ThreadParticipantManager(
                                threadId: widget.threadId!,
                                participants: widget.participants,
                                turnLimit: widget.turnLimit,
                                embedded: true,
                                onChanged: widget.onParticipantsChanged,
                                onOpenConfig: (agentId) => _closeAndRun(
                                  () => widget.onOpenAgent(agentId),
                                ),
                              ),
                        _ContextTab(
                          threadId: widget.threadId,
                          api: widget.api,
                          estimatedTokens: widget.estimatedTokens,
                          contextWindow: widget.contextWindow,
                          canCustomize: widget.threadId != null,
                          onResponse: () => _selectTab(3),
                        ),
                        if (_visitedTabs.contains(3))
                          widget.threadId == null
                              ? const _DisabledResponseTab()
                              : _LlmOverridesSheet(
                                  threadId: widget.threadId!,
                                  api: widget.api,
                                  onChanged: _onLlmChanged,
                                )
                        else
                          const SizedBox.shrink(),
                        if (_visitedTabs.contains(4))
                          _ToolOverridesSheet(
                            threadId: widget.threadId,
                            api: widget.api,
                            initialOverrides: widget.initialOverrides,
                            onChanged: _onToolChanged,
                            onOverridesSelected: _onPendingToolsChanged,
                          )
                        else
                          const SizedBox.shrink(),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _GeneralControlsTab extends StatelessWidget {
  final bool hasThread;
  final String threadMode;
  final bool modeChangeBusy;
  final int participantCount;
  final int activeRunCount;
  final int pendingApprovals;
  final ValueChanged<String>? onModeChanged;
  final VoidCallback onOpenAllAgents;
  final VoidCallback onOpenWorkspaceSettings;
  final VoidCallback onOpenMcp;
  final VoidCallback onOpenSkills;

  const _GeneralControlsTab({
    required this.hasThread,
    required this.threadMode,
    required this.modeChangeBusy,
    required this.participantCount,
    required this.activeRunCount,
    required this.pendingApprovals,
    required this.onModeChanged,
    required this.onOpenAllAgents,
    required this.onOpenWorkspaceSettings,
    required this.onOpenMcp,
    required this.onOpenSkills,
  });

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
    padding: const EdgeInsets.fromLTRB(16, 14, 16, 24),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          'Thread behavior',
          style: Theme.of(
            context,
          ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 5),
        const Text(
          'Choose how new messages are handled. Agent Threads route messages to the moderator or an @mentioned agent.',
          style: TextStyle(color: Colors.white54, height: 1.4),
        ),
        const SizedBox(height: 16),
        SizedBox(
          width: double.infinity,
          child: SegmentedButton<String>(
            segments: const [
              ButtonSegment(
                value: 'chat',
                icon: Icon(Icons.chat_bubble_outline, size: 18),
                label: Text('Chat Thread'),
              ),
              ButtonSegment(
                value: 'agent',
                icon: Icon(Icons.smart_toy_outlined, size: 18),
                label: Text('Agent Thread'),
              ),
            ],
            selected: {threadMode},
            showSelectedIcon: false,
            onSelectionChanged: !hasThread || modeChangeBusy
                ? null
                : (selected) {
                    final mode = selected.first;
                    if (mode != threadMode) onModeChanged?.call(mode);
                  },
          ),
        ),
        if (!hasThread || modeChangeBusy) ...[
          const SizedBox(height: 8),
          Text(
            !hasThread
                ? 'Send the first message before changing thread type.'
                : 'Thread type cannot change while work is running.',
            style: const TextStyle(fontSize: 12, color: Colors.white38),
          ),
        ],
        if (threadMode == 'agent') ...[
          const SizedBox(height: 20),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _StatusPill(
                icon: Icons.groups_outlined,
                label:
                    '$participantCount agent${participantCount == 1 ? '' : 's'}',
              ),
              _StatusPill(
                icon: Icons.play_circle_outline,
                label: '$activeRunCount running',
              ),
              _StatusPill(
                icon: Icons.fact_check_outlined,
                label:
                    '$pendingApprovals approval${pendingApprovals == 1 ? '' : 's'}',
              ),
            ],
          ),
          const SizedBox(height: 8),
          const Text(
            'Use the Agents tab to add agents, choose the moderator, configure heartbeats, or open detailed settings.',
            style: TextStyle(fontSize: 12, color: Colors.white54, height: 1.4),
          ),
        ],
        const SizedBox(height: 28),
        Text(
          'Workspace settings',
          style: Theme.of(
            context,
          ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 5),
        const Text(
          'Common configuration is available here without adding more buttons to the thread header.',
          style: TextStyle(color: Colors.white54),
        ),
        const SizedBox(height: 12),
        LayoutBuilder(
          builder: (context, constraints) {
            final width = constraints.maxWidth < 520
                ? constraints.maxWidth
                : (constraints.maxWidth - 10) / 2;
            return Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                _ControlShortcut(
                  width: width,
                  icon: Icons.smart_toy_outlined,
                  title: 'All agents',
                  subtitle: 'Browse agents and activity',
                  onTap: onOpenAllAgents,
                ),
                _ControlShortcut(
                  width: width,
                  icon: Icons.settings_outlined,
                  title: 'App settings',
                  subtitle: 'Models, media, Discord, security',
                  onTap: onOpenWorkspaceSettings,
                ),
                _ControlShortcut(
                  width: width,
                  icon: Icons.terminal_rounded,
                  title: 'MCP servers',
                  subtitle: 'External tools and connections',
                  onTap: onOpenMcp,
                ),
                _ControlShortcut(
                  width: width,
                  icon: Icons.auto_awesome_outlined,
                  title: 'Skills',
                  subtitle: 'Reusable instructions and expertise',
                  onTap: onOpenSkills,
                ),
              ],
            );
          },
        ),
      ],
    ),
  );
}

class _StatusPill extends StatelessWidget {
  final IconData icon;
  final String label;
  const _StatusPill({required this.icon, required this.label});

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
    decoration: BoxDecoration(
      color: Colors.white.withValues(alpha: .045),
      borderRadius: BorderRadius.circular(999),
      border: Border.all(color: Colors.white10),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 15, color: const Color(0xFFC4B5FD)),
        const SizedBox(width: 6),
        Text(label, style: const TextStyle(fontSize: 12)),
      ],
    ),
  );
}

class _ControlShortcut extends StatelessWidget {
  final double width;
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;
  const _ControlShortcut({
    required this.width,
    required this.icon,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) => SizedBox(
    width: width,
    child: Material(
      color: const Color(0xFF1D1D28),
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(13),
          child: Row(
            children: [
              Icon(icon, size: 20, color: const Color(0xFFC4B5FD)),
              const SizedBox(width: 11),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      subtitle,
                      style: const TextStyle(
                        fontSize: 11,
                        color: Colors.white54,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(
                Icons.chevron_right_rounded,
                size: 18,
                color: Colors.white30,
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

class _UnavailableControlTab extends StatelessWidget {
  final String message;
  const _UnavailableControlTab({required this.message});

  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(28),
      child: Text(
        message,
        textAlign: TextAlign.center,
        style: const TextStyle(color: Colors.white54),
      ),
    ),
  );
}

class _ActiveDot extends StatelessWidget {
  final bool active;
  const _ActiveDot({required this.active});
  @override
  Widget build(BuildContext context) => Container(
    width: 6,
    height: 6,
    decoration: BoxDecoration(
      color: active ? const Color(0xFF8B5CF6) : Colors.white24,
      shape: BoxShape.circle,
    ),
  );
}

class _TabLabel extends StatelessWidget {
  final String text;
  final bool active;

  const _TabLabel({required this.text, required this.active});

  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Text(text),
      if (active) ...[const SizedBox(width: 5), const _ActiveDot(active: true)],
    ],
  );
}

class _ContextTab extends StatefulWidget {
  final String? threadId;
  final ApiService api;
  final int estimatedTokens;
  final int contextWindow;
  final bool canCustomize;
  final VoidCallback onResponse;
  const _ContextTab({
    required this.threadId,
    required this.api,
    required this.estimatedTokens,
    required this.contextWindow,
    required this.canCustomize,
    required this.onResponse,
  });

  @override
  State<_ContextTab> createState() => _ContextTabState();
}

class _ContextTabState extends State<_ContextTab> {
  ThreadContext? _context;
  String? _error;
  bool _loading = false;

  @override
  void initState() {
    super.initState();
    if (widget.threadId != null) _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final result = await widget.api.getThreadContext(widget.threadId!);
      if (mounted)
        setState(() {
          _context = result;
          _loading = false;
        });
    } catch (_) {
      if (mounted)
        setState(() {
          _error = 'Context details are unavailable';
          _loading = false;
        });
    }
  }

  @override
  Widget build(BuildContext context) {
    final data = _context;
    final budget = data?.budget;
    final estimated = budget?.estimatedTokens ?? widget.estimatedTokens;
    final window = budget?.contextWindow ?? widget.contextWindow;
    final inputBudget = (budget?.inputBudget ?? window) > 0
        ? (budget?.inputBudget ?? window)
        : window;
    final ratio = inputBudget > 0
        ? (estimated / inputBudget).clamp(0.0, 1.0)
        : 0.0;
    final percent = (ratio * 100).round();
    final color = ratio < .5
        ? const Color(0xFF10B981)
        : ratio < .75
        ? const Color(0xFFF59E0B)
        : const Color(0xFFEF4444);
    return LayoutBuilder(
      builder: (context, constraints) {
        final sideBySide = constraints.maxWidth >= 600;
        return SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  const Expanded(
                    child: Text(
                      'Context usage',
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  if (_loading)
                    const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                  IconButton(
                    tooltip: 'Refresh context',
                    visualDensity: VisualDensity.compact,
                    onPressed: _loading || widget.threadId == null
                        ? null
                        : _load,
                    icon: const Icon(Icons.refresh_rounded, size: 18),
                  ),
                ],
              ),
              if (_error != null)
                _InlineError(message: _error!, onRetry: _load),
              if (sideBySide)
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: _budgetCard(
                        budget,
                        estimated,
                        window,
                        inputBudget,
                        ratio,
                        color,
                        percent,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: _compositionCard(data?.composition ?? const []),
                    ),
                  ],
                )
              else ...[
                _budgetCard(
                  budget,
                  estimated,
                  window,
                  inputBudget,
                  ratio,
                  color,
                  percent,
                ),
                const SizedBox(height: 10),
                _compositionCard(data?.composition ?? const []),
              ],
              const SizedBox(height: 10),
              _summaryCard(data?.summary),
              if (widget.canCustomize)
                Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton.icon(
                    onPressed: widget.onResponse,
                    icon: const Icon(Icons.tune_rounded, size: 16),
                    label: const Text('Customize response'),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }

  Widget _card(String title, Widget child) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: const Color(0xFF1C1C26),
      borderRadius: BorderRadius.circular(10),
      border: Border.all(color: Colors.white10),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
        const SizedBox(height: 12),
        child,
      ],
    ),
  );

  Widget _budgetCard(
    ContextBudget? budget,
    int estimated,
    int window,
    int inputBudget,
    double ratio,
    Color color,
    int percent,
  ) {
    final remaining =
        budget?.remainingTokens ??
        (inputBudget - estimated).clamp(0, inputBudget);
    final until = budget?.tokensUntilCompaction;
    final threshold = budget?.compactionAtTokens;
    return _card(
      'Input budget',
      Column(
        children: [
          Row(
            children: [
              _ContextGauge(
                ratio: ratio,
                color: color,
                percent: percent,
                size: 82,
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '$estimated tokens',
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const Text(
                      'Estimated input (chars/4)',
                      style: TextStyle(color: Colors.white54, fontSize: 11),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      '$remaining remaining input',
                      style: const TextStyle(
                        color: Colors.white70,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          _metric('Context window', _formatTokens(window)),
          _metric(
            'Max output reserve',
            _formatTokens(budget?.maxOutputTokens ?? 0),
          ),
          const SizedBox(height: 8),
          Text(
            until == null
                ? 'Compaction threshold unavailable'
                : '$until tokens until compaction${threshold == null ? '' : ' ($threshold)'}',
            style: const TextStyle(color: Colors.white60, fontSize: 11),
          ),
          if (until != null) ...[
            const SizedBox(height: 5),
            LinearProgressIndicator(
              value: threshold != null && threshold > 0
                  ? (estimated / threshold).clamp(0.0, 1.0)
                  : 0,
              minHeight: 4,
              backgroundColor: Colors.white10,
              color: color,
            ),
          ],
        ],
      ),
    );
  }

  Widget _metric(String label, String value) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 2),
    child: Row(
      children: [
        Expanded(
          child: Text(
            label,
            style: const TextStyle(color: Colors.white60, fontSize: 12),
          ),
        ),
        Text(value, style: const TextStyle(fontSize: 12)),
      ],
    ),
  );
  String _formatTokens(int value) => value == 0 ? '—' : value.toString();

  Widget _compositionCard(List<ContextCompositionItem> items) {
    final nonzero = items.where((item) => item.tokens > 0).toList();
    final total = nonzero.fold<int>(0, (sum, item) => sum + item.tokens);
    if (nonzero.isEmpty)
      return _card(
        'Composition',
        const Text(
          'Composition appears after messages are available.',
          style: TextStyle(color: Colors.white54, fontSize: 12),
        ),
      );
    return _card(
      'Composition',
      Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: nonzero
                .map(
                  (item) => Expanded(
                    flex: item.tokens,
                    child: Container(
                      height: 8,
                      color: _compositionColor(item.key),
                    ),
                  ),
                )
                .toList(),
          ),
          const SizedBox(height: 10),
          ...nonzero.map((item) {
            final share = total == 0 ? 0 : (item.tokens * 100 / total).round();
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(
                children: [
                  Container(
                    width: 8,
                    height: 8,
                    color: _compositionColor(item.key),
                  ),
                  const SizedBox(width: 7),
                  Expanded(
                    child: Text(
                      item.label,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 12),
                    ),
                  ),
                  Text(
                    '$share%  ${item.tokens} · ${item.messageCount} msg',
                    style: const TextStyle(color: Colors.white60, fontSize: 11),
                  ),
                ],
              ),
            );
          }),
        ],
      ),
    );
  }

  Color _compositionColor(String key) => switch (key) {
    'user' => const Color(0xFF8B5CF6),
    'assistant' => const Color(0xFF22D3EE),
    'tool_context' => const Color(0xFFF59E0B),
    'summaries' => const Color(0xFF10B981),
    'system_context' => const Color(0xFFEC4899),
    _ => const Color(0xFF60A5FA),
  };

  Widget _summaryCard(ContextSummary? summary) => _card(
    'Conversation summary',
    summary == null || summary.content.trim().isEmpty
        ? const Text(
            'A summary appears after the first completed response and refreshes after every completed response.',
            style: TextStyle(color: Colors.white54, height: 1.4, fontSize: 12),
          )
        : Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (summary.stale)
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 7,
                    vertical: 3,
                  ),
                  decoration: BoxDecoration(
                    color: Colors.white10,
                    borderRadius: BorderRadius.circular(5),
                  ),
                  child: const Text(
                    'Summary update pending',
                    style: TextStyle(color: Colors.white60, fontSize: 10),
                  ),
                ),
              if (summary.stale) const SizedBox(height: 8),
              MarkdownBody(
                data: summary.content,
                selectable: true,
                styleSheet: MarkdownStyleSheet(
                  p: const TextStyle(
                    color: Colors.white70,
                    height: 1.45,
                    fontSize: 12,
                  ),
                  h1: const TextStyle(
                    color: Color(0xFFE4E4E7),
                    fontSize: 17,
                    fontWeight: FontWeight.w700,
                  ),
                  h2: const TextStyle(
                    color: Color(0xFFE4E4E7),
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                  ),
                  h3: const TextStyle(
                    color: Color(0xFFE4E4E7),
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                  strong: const TextStyle(
                    color: Color(0xFFE4E4E7),
                    fontWeight: FontWeight.w700,
                  ),
                  em: const TextStyle(fontStyle: FontStyle.italic),
                  listBullet: const TextStyle(
                    color: Color(0xFFA78BFA),
                    fontSize: 12,
                  ),
                  code: TextStyle(
                    color: const Color(0xFFC4B5FD),
                    backgroundColor: Colors.white.withValues(alpha: 0.06),
                    fontFamily: 'monospace',
                    fontSize: 11,
                  ),
                  codeblockDecoration: BoxDecoration(
                    color: const Color(0xFF111118),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(color: Colors.white10),
                  ),
                  codeblockPadding: const EdgeInsets.all(12),
                  blockSpacing: 10,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'Updated through turn ${summary.turnCount} · thread at turn ${summary.currentTurnCount}',
                style: const TextStyle(color: Colors.white38, fontSize: 11),
              ),
            ],
          ),
  );
}

class _InlineError extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;
  const _InlineError({required this.message, required this.onRetry});
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: 8),
    child: Row(
      children: [
        Expanded(
          child: Text(
            message,
            style: const TextStyle(color: Colors.white54, fontSize: 11),
          ),
        ),
        TextButton(onPressed: onRetry, child: const Text('Retry')),
      ],
    ),
  );
}

class _ContextGauge extends StatelessWidget {
  final double ratio;
  final Color color;
  final int percent;
  final double size;

  const _ContextGauge({
    required this.ratio,
    required this.color,
    required this.percent,
    required this.size,
  });

  @override
  Widget build(BuildContext context) => SizedBox(
    width: size,
    height: size,
    child: Stack(
      alignment: Alignment.center,
      children: [
        Positioned.fill(
          child: CircularProgressIndicator(
            value: ratio,
            strokeWidth: 9,
            backgroundColor: Colors.white10,
            color: color,
          ),
        ),
        Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              '$percent%',
              style: const TextStyle(fontSize: 25, fontWeight: FontWeight.w700),
            ),
            Text(
              percent == 0 ? 'waiting' : 'in use',
              style: const TextStyle(color: Colors.white54, fontSize: 11),
            ),
          ],
        ),
      ],
    ),
  );
}

class _DisabledResponseTab extends StatelessWidget {
  const _DisabledResponseTab();
  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.tune_rounded, size: 42, color: Colors.white24),
          const SizedBox(height: 14),
          const Text(
            'Response settings are ready when your thread is created',
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 8),
          const Text(
            'Start a conversation first, then customize the model and response behavior for this thread.',
            textAlign: TextAlign.center,
            style: TextStyle(color: Colors.white54),
          ),
        ],
      ),
    ),
  );
}

// ── Tool Overrides ────────────────────────────────────────────────────────────

class _ToolOverridesSheet extends StatefulWidget {
  final String? threadId;
  final ApiService api;
  final ValueChanged<bool>? onChanged;
  final List<Map<String, dynamic>>? initialOverrides;
  final Function(List<Map<String, dynamic>>)? onOverridesSelected;

  const _ToolOverridesSheet({
    required this.threadId,
    required this.api,
    this.onChanged,
    this.initialOverrides,
    this.onOverridesSelected,
  });

  @override
  State<_ToolOverridesSheet> createState() => _ToolOverridesSheetState();
}

class _ToolOverridesSheetState extends State<_ToolOverridesSheet> {
  bool _isLoading = true;
  bool _isSaving = false;
  String? _loadError;
  List<_ServerState> _servers = [];
  final Map<String, List<bool>> _previousToolStates = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    if (mounted)
      setState(() {
        _isLoading = true;
        _loadError = null;
      });
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
          _loadError = null;
        });
    } catch (e) {
      if (mounted)
        setState(() {
          _isLoading = false;
          _loadError = e.toString();
        });
    }
  }

  String get _toolSummary {
    final disabledServers = _servers.where((s) => !s.enabled).length;
    final disabledTools = _servers.fold<int>(
      0,
      (n, s) => n + s.tools.where((t) => !t.enabled).length,
    );
    if (disabledServers == 0 && disabledTools == 0) return 'All tools enabled';
    return '${disabledTools} tool${disabledTools == 1 ? '' : 's'} disabled${disabledServers > 0 ? ' · $disabledServers server${disabledServers == 1 ? '' : 's'} disabled' : ''}';
  }

  void _restoreDefaults() => setState(() {
    for (final server in _servers) {
      server.enabled = true;
      for (final tool in server.tools) tool.enabled = true;
    }
  });

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
        widget.onChanged?.call(overrides.isNotEmpty);
      } else if (widget.onOverridesSelected != null) {
        widget.onOverridesSelected!(overrides);
      }

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              widget.threadId == null
                  ? 'MCP tool preferences ready for the new thread'
                  : 'MCP tool preferences saved',
            ),
            duration: const Duration(seconds: 2),
          ),
        );
      }
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
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 4, 20, 8),
          child: Row(
            children: [
              const Expanded(
                child: Text(
                  'Enable or disable MCP servers and individual tools for this thread.',
                  style: TextStyle(fontSize: 12, color: Colors.white54),
                ),
              ),
              FilledButton(
                onPressed: _isLoading || _isSaving || _loadError != null
                    ? null
                    : _save,
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
        if (_loadError != null)
          Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              children: [
                const Icon(Icons.error_outline, color: Colors.redAccent),
                const SizedBox(height: 6),
                const Text('Could not load MCP tools'),
                TextButton(onPressed: _load, child: const Text('Retry')),
              ],
            ),
          )
        else ...[
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    _toolSummary,
                    style: const TextStyle(color: Colors.white54, fontSize: 12),
                  ),
                ),
                TextButton(
                  onPressed: _isLoading || _isSaving ? null : _restoreDefaults,
                  child: const Text('Restore defaults'),
                ),
              ],
            ),
          ),
        ],
        const SizedBox(height: 12),
        // Server list
        if (_isLoading)
          const Padding(
            padding: EdgeInsets.all(32),
            child: CircularProgressIndicator(
              valueColor: AlwaysStoppedAnimation(Color(0xFF8B5CF6)),
            ),
          )
        else if (_loadError != null)
          const SizedBox.shrink()
        else if (_servers.isEmpty)
          Padding(
            padding: const EdgeInsets.all(32),
            child: Text(
              'No active MCP servers configured.',
              style: TextStyle(color: Colors.white.withValues(alpha: 0.4)),
            ),
          )
        else
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              itemCount: _servers.length,
              itemBuilder: (context, index) =>
                  _buildServerTile(_servers[index]),
            ),
          ),
      ],
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
                          server.tools.isEmpty
                              ? 'No tools'
                              : '${server.tools.where((t) => t.enabled).length} of ${server.tools.length} enabled',
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
                        if (!v) {
                          _previousToolStates[server.id] = server.tools
                              .map((t) => t.enabled)
                              .toList();
                        }
                        server.enabled = v;
                        if (!v) {
                          for (final t in server.tools) t.enabled = false;
                        } else {
                          final previous = _previousToolStates[server.id];
                          for (var i = 0; i < server.tools.length; i++) {
                            server.tools[i].enabled =
                                previous != null && i < previous.length
                                ? previous[i]
                                : true;
                          }
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
  final ValueChanged<bool>? onChanged;

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
  final ScrollController _bodyScrollController = ScrollController();
  final ScrollController _categoryScrollController = ScrollController();
  String _search = '';
  String _selectedCategory = 'Basic';
  final Map<String, bool> _expandedCategories = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _searchController.dispose();
    _bodyScrollController.dispose();
    _categoryScrollController.dispose();
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
      widget.onChanged?.call(updated.overrides.isNotEmpty);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _isSaving = false;
      });
    }
  }

  Future<void> _clearAll() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Clear all overrides?'),
        content: const Text(
          'This removes every custom response setting for this thread.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Clear all'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => _isSaving = true);
    try {
      final updated = await widget.api.clearThreadLlmOverrides(widget.threadId);
      if (!mounted) return;
      setState(() {
        _overrides = updated;
        _isSaving = false;
        _error = null;
      });
      widget.onChanged?.call(updated.overrides.isNotEmpty);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _isSaving = false;
      });
    }
  }

  void _setOverride(String key, dynamic value) {
    if (value is String && value.trim().isEmpty) {
      _clearOne(key);
      return;
    }
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
    _save(current);
  }

  @override
  Widget build(BuildContext context) {
    final overrides = _overrides;
    if (_isLoading) return const Center(child: CircularProgressIndicator());
    if (_error != null)
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(_error!, style: const TextStyle(color: Colors.redAccent)),
            TextButton(onPressed: _load, child: const Text('Retry')),
          ],
        ),
      );
    if (overrides == null) return const SizedBox.shrink();
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  overrides.overrides.isEmpty
                      ? 'Falls back to global LLM settings.'
                      : '${overrides.overrides.length} custom setting${overrides.overrides.length == 1 ? '' : 's'} on this thread.',
                  style: const TextStyle(color: Colors.white54, fontSize: 12),
                ),
              ),
              if (overrides.overrides.isNotEmpty)
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
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: TextField(
            controller: _searchController,
            onChanged: (v) => setState(() {
              _search = v.trim().toLowerCase();
              if (_search.isNotEmpty) _selectedCategory = 'Search results';
            }),
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
        const SizedBox(height: 8),
        Expanded(
          child: LayoutBuilder(
            builder: (context, constraints) => _buildBody(
              overrides,
              _bodyScrollController,
              constraints.maxWidth,
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildBody(
    ThreadLlmOverrides overrides,
    ScrollController scrollController,
    double width,
  ) {
    final categories = <String, List<String>>{
      'Basic': ['system_prompt', 'model', 'temperature', 'max_tokens'],
      'Connection': ['provider', 'api_url', 'api_key'],
      'Context & limits': [
        'max_iterations',
        'context_window',
        'stream_timeout',
        'video_tool_timeout',
        'compaction_threshold',
        'preserve_recent',
      ],
      'Tool behavior': ['tool_result_max_chars'],
      'Image generation': [
        'image_enabled',
        'image_model',
        'image_api_url',
        'image_provider',
      ],
      'Speech & video': [
        'audio_enabled',
        'tts_provider',
        'tts_api_url',
        'tts_api_key',
        'tts_model',
        'tts_voice',
        'tts_format',
        'tts_timeout',
        'lipsync_enabled',
        'video_enabled',
      ],
      'Vision': [
        'vision_enabled',
        'vision_api_url',
        'vision_api_key',
        'vision_model',
        'vision_provider',
        'vision_max_tokens',
      ],
    };
    final known = categories.values.expand((v) => v).toSet();
    final other = overrides.keys.where((k) => !known.contains(k)).toList();
    if (other.isNotEmpty) categories['Other advanced'] = other;
    final matching = <String, List<String>>{};
    for (final category in categories.entries) {
      final keys = category.value.where((key) {
        final entry = overrides.schema[key];
        if (entry == null) return false;
        if (_search.isEmpty) return true;
        return key.toLowerCase().contains(_search) ||
            entry.label.toLowerCase().contains(_search);
      }).toList();
      if (keys.isNotEmpty) matching[category.key] = keys;
    }
    if (matching.isEmpty) {
      return Center(
        child: Text(
          'No matches for "$_search"',
          style: const TextStyle(color: Colors.white54),
        ),
      );
    }

    if (width >= 600) {
      return _buildDesktopBody(overrides, categories, matching);
    }

    final activeKeys = overrides.overrides.keys
        .where((key) => matching.values.expand((value) => value).contains(key))
        .toList();
    return ListView(
      controller: scrollController,
      padding: const EdgeInsets.symmetric(vertical: 8),
      children: [
        if (activeKeys.isNotEmpty)
          _CategoryPanel(
            title: 'Active overrides',
            keys: activeKeys,
            expanded: true,
            child: Wrap(
              spacing: 6,
              runSpacing: 6,
              children: activeKeys
                  .map(
                    (key) => Chip(
                      label: Text(overrides.schema[key]?.label ?? key),
                      onDeleted: () => _clearOne(key),
                    ),
                  )
                  .toList(),
            ),
          ),
        ...matching.entries.map(
          (category) => _CategoryPanel(
            title: category.key,
            keys: category.value,
            expanded:
                category.key == 'Basic' ||
                _search.isNotEmpty ||
                (_expandedCategories[category.key] ?? false),
            onToggle: () => setState(
              () => _expandedCategories[category.key] =
                  !(_expandedCategories[category.key] ?? false),
            ),
            child: Column(
              children: category.value
                  .map(
                    (key) => _buildRow(key, overrides.schema[key]!, overrides),
                  )
                  .toList(),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildDesktopBody(
    ThreadLlmOverrides overrides,
    Map<String, List<String>> categories,
    Map<String, List<String>> matching,
  ) {
    final searching = _search.isNotEmpty;
    final selected = searching
        ? 'Search results'
        : matching.containsKey(_selectedCategory)
        ? _selectedCategory
        : 'Basic';
    final selectedKeys = searching
        ? matching.values.expand((keys) => keys).toList()
        : (matching[selected] ?? const <String>[]);
    final activeCount = overrides.overrides.length;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SizedBox(
          width: 176,
          child: ListView(
            controller: _categoryScrollController,
            padding: const EdgeInsets.only(bottom: 8),
            children: [
              if (activeCount > 0)
                Padding(
                  padding: const EdgeInsets.fromLTRB(8, 8, 8, 2),
                  child: Text(
                    '$activeCount active override${activeCount == 1 ? '' : 's'}',
                    style: const TextStyle(color: Colors.white54, fontSize: 11),
                  ),
                ),
              if (searching)
                _buildCategoryRailItem(
                  'Search results',
                  selected,
                  selectedKeys.length,
                  activeCount,
                ),
              ...categories.entries.map(
                (category) => _buildCategoryRailItem(
                  category.key,
                  selected,
                  category.value.length,
                  category.value.where(overrides.overrides.containsKey).length,
                ),
              ),
            ],
          ),
        ),
        const VerticalDivider(width: 1, color: Colors.white12),
        Expanded(
          child: ListView(
            controller: _bodyScrollController,
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 16),
            children: [
              if (searching)
                ...matching.entries.expand(
                  (category) => [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(4, 8, 4, 4),
                      child: Text(
                        category.key,
                        style: const TextStyle(
                          color: Colors.white54,
                          fontSize: 11,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    ...category.value.map(
                      (key) =>
                          _buildRow(key, overrides.schema[key]!, overrides),
                    ),
                  ],
                )
              else ...[
                Padding(
                  padding: const EdgeInsets.fromLTRB(4, 4, 4, 8),
                  child: Text(
                    selected,
                    style: const TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                ...selectedKeys.map(
                  (key) => _buildRow(key, overrides.schema[key]!, overrides),
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildCategoryRailItem(
    String title,
    String selected,
    int count,
    int activeCount,
  ) {
    final isSelected = title == selected;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      child: ListTile(
        dense: true,
        visualDensity: VisualDensity.compact,
        selected: isSelected,
        selectedTileColor: const Color(0xFF8B5CF6).withValues(alpha: .14),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        title: Text(
          title,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontSize: 12),
        ),
        subtitle: Text(
          '$count setting${count == 1 ? '' : 's'}',
          style: const TextStyle(color: Colors.white38, fontSize: 10),
        ),
        trailing: activeCount > 0 ? const _ActiveDot(active: true) : null,
        onTap: () => setState(() {
          _selectedCategory = title;
          if (_search.isNotEmpty && title != 'Search results') {
            _searchController.clear();
            _search = '';
          }
        }),
      ),
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
                                key: ValueKey<String>(key),
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
                                key: ValueKey<String>(key),
                                keyName: key,
                                initial: _isSecret(key)
                                    ? ''
                                    : displayValue?.toString() ?? '',
                                isOverridden: isOverridden,
                                isSaving: _isSaving,
                                multiline:
                                    key == 'system_prompt' ||
                                    key == 'api_key' ||
                                    key == 'tts_api_key' ||
                                    key == 'vision_api_key',
                                secret: _isSecret(key),
                                onSubmit: (v) {
                                  if (v.isNotEmpty) {
                                    _setOverride(key, v);
                                  } else if (!_isSecret(key)) {
                                    _clearOne(key);
                                  }
                                },
                                onReset: isOverridden
                                    ? () => _clearOne(key)
                                    : null,
                              ),
                      ),
                    ],
                  ),
                if (_isSecret(key))
                  Text(
                    isOverridden
                        ? 'Thread credential configured'
                        : effective != null && effective != ''
                        ? 'Using global credential'
                        : 'Not configured',
                    style: const TextStyle(color: Colors.white38, fontSize: 11),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  static bool _isSecret(String key) =>
      const {'api_key', 'tts_api_key', 'vision_api_key'}.contains(key);
}

class _CategoryPanel extends StatelessWidget {
  final String title;
  final List<String> keys;
  final bool expanded;
  final Widget child;
  final VoidCallback? onToggle;

  const _CategoryPanel({
    required this.title,
    required this.keys,
    required this.expanded,
    required this.child,
    this.onToggle,
  });

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
    child: Container(
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: .025),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        children: [
          ListTile(
            minVerticalPadding: 4,
            title: Text(
              title,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
            subtitle: Text(
              '${keys.length} setting${keys.length == 1 ? '' : 's'}',
              style: const TextStyle(color: Colors.white38, fontSize: 11),
            ),
            trailing: Icon(expanded ? Icons.expand_less : Icons.expand_more),
            onTap: onToggle,
          ),
          if (expanded) child,
        ],
      ),
    ),
  );
}

class _NumberField extends StatefulWidget {
  final String keyName;
  final Object? initial;
  final bool isOverridden;
  final bool isSaving;
  final ValueChanged<Object?> onSubmit;
  final VoidCallback? onReset;

  const _NumberField({
    super.key,
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
  final bool secret;
  final ValueChanged<String> onSubmit;
  final VoidCallback? onReset;

  const _StringField({
    super.key,
    required this.keyName,
    required this.initial,
    required this.isOverridden,
    required this.isSaving,
    required this.multiline,
    this.secret = false,
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
            obscureText: widget.secret,
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
