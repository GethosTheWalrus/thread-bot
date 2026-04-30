import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:threadbot/models/message.dart';
import 'package:url_launcher/url_launcher.dart';

class ChatMessageList extends StatelessWidget {
  final List<Message> messages;
  final ScrollController scrollController;
  final bool isSending;

  const ChatMessageList({
    super.key,
    required this.messages,
    required this.scrollController,
    this.isSending = false,
  });

  @override
  Widget build(BuildContext context) {
    // Pre-compute which tool_result indices are claimed by a tool_call group
    // so we can hide them from the top-level list (they render inside the call bubble).
    final claimedResultIndices = <int>{};
    final toolCallResults = <int, List<Message>>{};

    for (var i = 0; i < messages.length; i++) {
      if (messages[i].isToolCall) {
        final results = <Message>[];
        for (var j = i + 1; j < messages.length; j++) {
          if (messages[j].isToolResult) {
            results.add(messages[j]);
            claimedResultIndices.add(j);
          } else {
            break;
          }
        }
        toolCallResults[i] = results;
      }
    }

    // Pre-compute which tool_call and thinking indices are claimed by a following assistant message
    // so they render inside the assistant bubble under "THREADBOT".
    final claimedToolCallIndices = <int>{};
    final claimedThinkingIndices = <int>{};
    final assistantPreItems = <int, List<_PreAssistantItem>>{};

    for (var i = 0; i < messages.length; i++) {
      // Claim preceding tool_call/thinking for ALL assistant messages, including
      // the empty placeholder (temp-ast-*). This ensures tool_calls render inline
      // under the THREADBOT header rather than as standalone bubbles above it.
      if (messages[i].isAssistant) {
        final items = <_PreAssistantItem>[];
        // Walk backwards from the assistant message to collect preceding tool_call/thinking
        for (var j = i - 1; j >= 0; j--) {
          if (messages[j].isToolCall) {
            claimedToolCallIndices.add(j);
            items.insert(0, _PreAssistantItem(
              toolCallGroup: _ToolCallGroup(
                message: messages[j],
                results: toolCallResults[j] ?? [],
              ),
            ));
          } else if (messages[j].isThinking) {
            claimedThinkingIndices.add(j);
            items.insert(0, _PreAssistantItem(thinking: messages[j]));
          } else if (messages[j].isToolResult && claimedResultIndices.contains(j)) {
            // Skip — already claimed by a tool_call
            continue;
          } else {
            break;
          }
        }
        if (items.isNotEmpty) {
          assistantPreItems[i] = items;
        }
      }
    }

    // Pre-compute timeline steps for each assistant message.
    // Each conversational turn gets its own node: thinking, tool call,
    // tool result processing, and final text response.
    final assistantTimelines = <int, List<_TimelineStep>>{};
    for (var i = 0; i < messages.length; i++) {
      if (!messages[i].isAssistant) continue;
      final steps = <_TimelineStep>[];
      final pre = assistantPreItems[i] ?? [];

      if (pre.isNotEmpty) {
        // Completed assistant message — derive from claimed preItems
        for (final item in pre) {
          if (item.isThinking) {
            steps.add(const _TimelineStep(_TimelineStepType.thinking));
          } else if (item.isToolCall) {
            steps.add(const _TimelineStep(_TimelineStepType.toolCall));
            // Each tool result is its own node
            for (final _ in item.toolCallGroup!.results) {
              steps.add(const _TimelineStep(_TimelineStepType.toolResult));
            }
          }
        }
      } else {
        // Streaming or no preItems — scan backwards from this assistant to the
        // previous user message and build timeline from the raw message list.
        for (var j = i - 1; j >= 0; j--) {
          if (messages[j].isUser) break;
          if (messages[j].isThinking) {
            steps.insert(0, const _TimelineStep(_TimelineStepType.thinking));
          } else if (messages[j].isToolCall) {
            steps.insert(0, const _TimelineStep(_TimelineStepType.toolCall));
          } else if (messages[j].isToolResult) {
            steps.insert(0, const _TimelineStep(_TimelineStepType.toolResult));
          } else if (messages[j].isSystem && messages[j].metadata?['type'] == 'compaction_event') {
            steps.insert(0, const _TimelineStep(_TimelineStepType.compaction));
          } else if (messages[j].isSystem) {
            continue;
          } else {
            break;
          }
        }
      }

      // Final step: text generation (always present for assistant messages)
      steps.add(_TimelineStep(
        messages[i].content.isEmpty
            ? _TimelineStepType.textActive
            : _TimelineStepType.text,
      ));
      assistantTimelines[i] = steps;
    }

    return ListView.builder(
      controller: scrollController,
      padding: const EdgeInsets.symmetric(vertical: 24),
      itemCount: messages.length,
      itemBuilder: (context, index) {
        final msg = messages[index];
        if (msg.isCompactionSummary) return _CompactionDivider(message: msg);
        // Hide thinking messages claimed by an assistant message
        if (msg.isThinking && claimedThinkingIndices.contains(index)) {
          return const SizedBox.shrink();
        }
        // Unclaimed thinking (still streaming, no assistant response yet)
        if (msg.isThinking) {
          return _ThinkingBubble(message: msg);
        }
        // Hide tool_calls claimed by an assistant message
        if (msg.isToolCall && claimedToolCallIndices.contains(index)) {
          return const SizedBox.shrink();
        }
        // Unclaimed tool_call (no assistant message follows at all — rare edge case)
        if (msg.isToolCall) {
          final hasAssistantAfter = messages.skip(index + 1).any(
            (m) => m.isAssistant,
          );
          return _ToolCallBubble(
            message: msg,
            isLoading: isSending && !hasAssistantAfter,
            results: toolCallResults[index] ?? [],
          );
        }
        // Hide tool_results that are claimed by a tool_call group
        if (msg.isToolResult && claimedResultIndices.contains(index)) {
          return const SizedBox.shrink();
        }
        // Unclaimed tool_result (shouldn't happen, but render standalone just in case)
        if (msg.isToolResult) return _ToolResultBubble(message: msg);
        if (msg.isSystem) return const SizedBox.shrink();
        return _ChatBubble(
          message: msg,
          preItems: assistantPreItems[index] ?? [],
          timelineSteps: assistantTimelines[index] ?? [],
          isLoading: isSending && msg.content.isEmpty,
        );
      },
    );
  }
}

// ── Compaction Divider ────────────────────────────────────────────────────────

class _CompactionDivider extends StatelessWidget {
  final Message message;
  const _CompactionDivider({required this.message});

  @override
  Widget build(BuildContext context) {
    final count = message.metadata?['compacted_count'] ?? message.metadata?['original_message_count'];
    final label = count != null
        ? '📋 $count earlier messages summarized'
        : '📋 Conversation summarized';

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
      child: Row(
        children: [
          Expanded(
            child: Divider(color: Colors.white.withValues(alpha: 0.08), thickness: 1),
          ),
          const SizedBox(width: 12),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(20),
              color: const Color(0xFF8B5CF6).withValues(alpha: 0.08),
              border: Border.all(color: const Color(0xFF8B5CF6).withValues(alpha: 0.2)),
            ),
            child: Text(
              label,
              style: const TextStyle(
                fontSize: 11,
                color: Color(0xFF8B5CF6),
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Divider(color: Colors.white.withValues(alpha: 0.08), thickness: 1),
          ),
        ],
      ),
    );
  }
}

// ── Tool Call Bubble ──────────────────────────────────────────────────────────

class _ToolCallBubble extends StatefulWidget {
  final Message message;
  final bool isLoading;
  final List<Message> results;
  const _ToolCallBubble({
    required this.message,
    this.isLoading = false,
    this.results = const [],
  });

  @override
  State<_ToolCallBubble> createState() => _ToolCallBubbleState();
}

class _ToolCallBubbleState extends State<_ToolCallBubble> {
  /// Parse "Calling server1:tool1, server2:tool2" into individual tool names.
  List<String> _parseToolCalls(String content) {
    var body = content;
    if (body.startsWith('Calling ')) {
      body = body.substring('Calling '.length);
    }
    return body
        .split(',')
        .map((s) => s.trim())
        .where((s) => s.isNotEmpty)
        .toList();
  }

  static bool _isError(String content) {
    if (content.startsWith('Error executing tool:') ||
        content.startsWith('Error:') ||
        content == 'Tool not found') {
      return true;
    }
    // Detect JSON error responses like {"error": "...", ...}
    try {
      final parsed = jsonDecode(content);
      if (parsed is Map && parsed.containsKey('error')) return true;
    } catch (_) {}
    return false;
  }

  @override
  Widget build(BuildContext context) {
    final tools = _parseToolCalls(widget.message.content);

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 4),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(width: 48), // align with assistant messages
              Flexible(
                child: _buildToolList(tools),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildToolList(List<String> tools) {
    // Extract per-tool arguments from metadata
    final toolCalls = widget.message.metadata?['tool_calls'] as List<dynamic>?;

    // Determine per-chip loading: a chip is loading if the overall bubble
    // is loading AND this specific chip doesn't have a result yet.
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: List.generate(tools.length, (i) {
        final result = i < widget.results.length ? widget.results[i] : null;
        final succeeded = result != null && !_isError(result.content);
        final failed = result != null && _isError(result.content);
        final chipLoading = widget.isLoading && result == null;

        // Extract arguments for this specific tool call
        String? toolInput;
        if (toolCalls != null && i < toolCalls.length) {
          final tc = toolCalls[i] as Map<String, dynamic>?;
          final fn = tc?['function'] as Map<String, dynamic>?;
          toolInput = fn?['arguments'] as String?;
        }

        return _ToolCallChip(
          tool: tools[i],
          isLoading: chipLoading,
          succeeded: succeeded,
          failed: failed,
          result: result,
          toolInput: toolInput,
        );
      }),
    );
  }
}

/// Individual tool call chip with status icon and collapsible result.
class _ToolCallChip extends StatefulWidget {
  final String tool;
  final bool isLoading;
  final bool succeeded;
  final bool failed;
  final Message? result;
  final String? toolInput;

  const _ToolCallChip({
    required this.tool,
    this.isLoading = false,
    this.succeeded = false,
    this.failed = false,
    this.result,
    this.toolInput,
  });

  @override
  State<_ToolCallChip> createState() => _ToolCallChipState();
}

class _ToolCallChipState extends State<_ToolCallChip>
    with SingleTickerProviderStateMixin {
  bool _expanded = false;
  late final AnimationController _pulseController;
  late final Animation<double> _pulseAnimation;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    );
    _pulseAnimation = Tween<double>(begin: 0.45, end: 0.85).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );
    if (widget.isLoading) _pulseController.repeat(reverse: true);
  }

  @override
  void didUpdateWidget(_ToolCallChip oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.isLoading && !_pulseController.isAnimating) {
      _pulseController.repeat(reverse: true);
    } else if (!widget.isLoading && _pulseController.isAnimating) {
      _pulseController.stop();
      _pulseController.value = 1.0; // full opacity when done
    }
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final hasExpandableContent = widget.toolInput != null || widget.result != null;

    Widget chip = Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // ── Chip row ───────────────────────────────────────────────
          GestureDetector(
            onTap: hasExpandableContent
                ? () => setState(() => _expanded = !_expanded)
                : null,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(6),
                color: const Color(0xFF8B5CF6).withValues(alpha: 0.06),
                border: Border.all(
                  color: const Color(0xFF8B5CF6).withValues(alpha: 0.12),
                ),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.build_outlined, size: 12, color: Color(0xFF8B5CF6)),
                  const SizedBox(width: 6),
                  Flexible(
                    child: Text(
                      widget.tool,
                      style: const TextStyle(
                        fontSize: 12,
                        color: Color(0xFF8B5CF6),
                        fontStyle: FontStyle.italic,
                      ),
                    ),
                  ),
                  // Status icon
                  if (widget.isLoading && !widget.succeeded && !widget.failed) ...[
                    const SizedBox(width: 6),
                    SizedBox(
                      width: 13,
                      height: 13,
                      child: CircularProgressIndicator(
                        strokeWidth: 1.5,
                        color: const Color(0xFF8B5CF6).withValues(alpha: 0.7),
                      ),
                    ),
                  ] else if (widget.succeeded || widget.failed) ...[
                    const SizedBox(width: 6),
                    Icon(
                      widget.succeeded ? Icons.check_circle_rounded : Icons.cancel_rounded,
                      size: 13,
                      color: widget.succeeded
                          ? const Color(0xFF22C55E)
                          : const Color(0xFFEF4444),
                    ),
                  ],
                  // Expand/collapse chevron when expandable content exists
                  if (hasExpandableContent) ...[
                    const SizedBox(width: 4),
                    Icon(
                      _expanded ? Icons.expand_less : Icons.expand_more,
                      size: 14,
                      color: const Color(0xFF8B5CF6).withValues(alpha: 0.6),
                    ),
                  ],
                ],
              ),
            ),
          ),

          // ── Collapsible input + result block ───────────────────────
          if (_expanded && hasExpandableContent)
            Padding(
              padding: const EdgeInsets.only(top: 2, left: 4),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (widget.toolInput != null)
                    _CollapsibleResultBlock(
                      content: widget.toolInput!,
                      label: 'input',
                    ),
                  if (widget.toolInput != null && widget.result != null)
                    const SizedBox(height: 4),
                  if (widget.result != null)
                    _CollapsibleResultBlock(
                      content: widget.result!.content,
                      label: 'output',
                    ),
                ],
              ),
            ),
        ],
      ),
    );

    // Wrap with pulse animation when this chip is still loading
    if (widget.isLoading) {
      return AnimatedBuilder(
        animation: _pulseAnimation,
        builder: (_, child) => Opacity(
          opacity: _pulseAnimation.value,
          child: child,
        ),
        child: chip,
      );
    }
    return chip;
  }
}

/// Formatted code block for tool input/result content (JSON or plain text).
class _CollapsibleResultBlock extends StatelessWidget {
  final String content;
  final String label;
  const _CollapsibleResultBlock({required this.content, this.label = 'output'});

  String _format(String raw) {
    try {
      final parsed = jsonDecode(raw);
      return const JsonEncoder.withIndent('  ').convert(parsed);
    } catch (_) {
      return raw;
    }
  }

  bool _isJson(String raw) {
    try {
      jsonDecode(raw);
      return true;
    } catch (_) {
      return false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final formatted = _format(content);
    final isJson = _isJson(content);

    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(6),
        color: const Color(0xFF111118),
        border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Language label bar
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(
              borderRadius: const BorderRadius.vertical(top: Radius.circular(6)),
              color: Colors.white.withValues(alpha: 0.03),
              border: Border(
                bottom: BorderSide(color: Colors.white.withValues(alpha: 0.06)),
              ),
            ),
            child: Row(
              children: [
                Icon(
                  isJson ? Icons.data_object : Icons.terminal_rounded,
                  size: 11,
                  color: const Color(0xFF71717A),
                ),
                const SizedBox(width: 5),
                Text(
                  isJson ? '$label (json)' : label,
                  style: const TextStyle(
                    fontSize: 10,
                    color: Color(0xFF71717A),
                    fontFamily: 'monospace',
                  ),
                ),
              ],
            ),
          ),
          // Content
          Padding(
            padding: const EdgeInsets.all(10),
            child: SelectableText(
              formatted,
              style: const TextStyle(
                fontSize: 11,
                fontFamily: 'monospace',
                color: Color(0xFFA1A1AA),
                height: 1.5,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

// ── Standalone Tool Result Bubble (fallback for unclaimed results) ────────────

class _ToolResultBubble extends StatefulWidget {
  final Message message;
  const _ToolResultBubble({required this.message});

  @override
  State<_ToolResultBubble> createState() => _ToolResultBubbleState();
}

class _ToolResultBubbleState extends State<_ToolResultBubble> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final toolName = widget.message.metadata?['tool_name'] as String? ?? 'Tool';

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 4),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(width: 48),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    GestureDetector(
                      onTap: () => setState(() => _expanded = !_expanded),
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(6),
                          color: Colors.white.withValues(alpha: 0.03),
                          border: Border.all(color: Colors.white.withValues(alpha: 0.08)),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(Icons.terminal_rounded, size: 12, color: Color(0xFF71717A)),
                            const SizedBox(width: 6),
                            Text(
                              toolName,
                              style: const TextStyle(fontSize: 11, color: Color(0xFF71717A)),
                            ),
                            const SizedBox(width: 4),
                            Icon(
                              _expanded ? Icons.expand_less : Icons.expand_more,
                              size: 14,
                              color: const Color(0xFF71717A),
                            ),
                          ],
                        ),
                      ),
                    ),
                    if (_expanded)
                      Padding(
                        padding: const EdgeInsets.only(top: 2),
                        child: _CollapsibleResultBlock(content: widget.message.content),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

// ── Tool Call Group ───────────────────────────────────────────────────────────

class _ToolCallGroup {
  final Message message;
  final List<Message> results;
  const _ToolCallGroup({required this.message, required this.results});
}

/// A single item (thinking or tool_call group) that precedes an assistant message.
/// Stored in chronological order so rendering preserves the original sequence.
class _PreAssistantItem {
  final Message? thinking;
  final _ToolCallGroup? toolCallGroup;
  const _PreAssistantItem({this.thinking, this.toolCallGroup});

  bool get isThinking => thinking != null;
  bool get isToolCall => toolCallGroup != null;
}

// ── Thinking Bubble (collapsible, standalone for unclaimed) ───────────────────

class _ThinkingBubble extends StatefulWidget {
  final Message message;
  const _ThinkingBubble({required this.message});

  @override
  State<_ThinkingBubble> createState() => _ThinkingBubbleState();
}

class _ThinkingBubbleState extends State<_ThinkingBubble> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 4),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(width: 48), // align with assistant messages
              Flexible(
                child: GestureDetector(
                  onTap: () => setState(() => _expanded = !_expanded),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(6),
                          color: const Color(0xFFF59E0B).withValues(alpha: 0.06),
                          border: Border.all(
                            color: const Color(0xFFF59E0B).withValues(alpha: 0.12),
                          ),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(Icons.psychology_outlined, size: 12, color: Color(0xFFF59E0B)),
                            const SizedBox(width: 6),
                            const Text(
                              'Thinking',
                              style: TextStyle(
                                fontSize: 12,
                                color: Color(0xFFF59E0B),
                                fontStyle: FontStyle.italic,
                              ),
                            ),
                            const SizedBox(width: 4),
                            Icon(
                              _expanded ? Icons.expand_less : Icons.expand_more,
                              size: 14,
                              color: const Color(0xFFF59E0B).withValues(alpha: 0.6),
                            ),
                          ],
                        ),
                      ),
                      if (_expanded)
                        Padding(
                          padding: const EdgeInsets.only(top: 4),
                          child: Container(
                            width: double.infinity,
                            padding: const EdgeInsets.all(10),
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(6),
                              color: const Color(0xFF111118),
                              border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
                            ),
                            child: SelectableText(
                              widget.message.content,
                              style: const TextStyle(
                                fontSize: 12,
                                color: Color(0xFFA1A1AA),
                                height: 1.5,
                              ),
                            ),
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
    );
  }
}

/// Inline thinking block rendered within an assistant bubble.
class _InlineThinkingBlock extends StatefulWidget {
  final Message message;
  const _InlineThinkingBlock({required this.message});

  @override
  State<_InlineThinkingBlock> createState() => _InlineThinkingBlockState();
}

class _InlineThinkingBlockState extends State<_InlineThinkingBlock> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: GestureDetector(
        onTap: () => setState(() => _expanded = !_expanded),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(6),
                color: const Color(0xFFF59E0B).withValues(alpha: 0.06),
                border: Border.all(
                  color: const Color(0xFFF59E0B).withValues(alpha: 0.12),
                ),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.psychology_outlined, size: 12, color: Color(0xFFF59E0B)),
                  const SizedBox(width: 6),
                  const Text(
                    'Thinking',
                    style: TextStyle(
                      fontSize: 12,
                      color: Color(0xFFF59E0B),
                      fontStyle: FontStyle.italic,
                    ),
                  ),
                  const SizedBox(width: 4),
                  Icon(
                    _expanded ? Icons.expand_less : Icons.expand_more,
                    size: 14,
                    color: const Color(0xFFF59E0B).withValues(alpha: 0.6),
                  ),
                ],
              ),
            ),
            if (_expanded)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(6),
                    color: const Color(0xFF111118),
                    border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
                  ),
                  child: SelectableText(
                    widget.message.content,
                    style: const TextStyle(
                      fontSize: 12,
                      color: Color(0xFFA1A1AA),
                      height: 1.5,
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

// ── Timeline Step Types ──────────────────────────────────────────────────────

enum _TimelineStepType { thinking, toolCall, toolResult, compaction, text, textActive }

class _TimelineStep {
  final _TimelineStepType type;
  const _TimelineStep(this.type);
}

/// Compact horizontal timeline showing the bot's progression through a response.
/// Renders as: (start) ── step ── step ── ... ── (end) ►
class _ResponseTimeline extends StatelessWidget {
  final List<_TimelineStep> steps;
  const _ResponseTimeline({required this.steps});

  @override
  Widget build(BuildContext context) {
    if (steps.length <= 1) return const SizedBox.shrink();

    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Start node
          _buildTerminalNode(),
          _buildConnector(),
          for (var i = 0; i < steps.length; i++) ...[
            _buildStepNode(steps[i], i == steps.length - 1),
            if (i < steps.length - 1) _buildConnector(),
          ],
          _buildConnector(),
          // End chevron — indicates reading direction (offset to align connector with chevron point)
          Transform.translate(
            offset: const Offset(-3, 0),
            child: Icon(
              Icons.chevron_right_rounded,
              size: 18,
              color: Colors.white.withValues(alpha: 0.35),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildTerminalNode() {
    return Container(
      width: 8,
      height: 8,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: Colors.white.withValues(alpha: 0.25),
      ),
    );
  }

  Widget _buildConnector() {
    return Container(
      width: 12,
      height: 1,
      color: Colors.white.withValues(alpha: 0.15),
    );
  }

  Widget _buildStepNode(_TimelineStep step, bool isLast) {
    final config = _stepConfig(step);
    final isActive = step.type == _TimelineStepType.textActive;

    Widget node = Container(
      width: 20,
      height: 20,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: config.color.withValues(alpha: isActive ? 0.2 : 0.12),
        border: Border.all(
          color: config.color.withValues(alpha: isActive ? 0.6 : 0.3),
          width: 1,
        ),
      ),
      child: Icon(config.icon, size: 10, color: config.color),
    );

    if (isActive) {
      node = _PulsingWidget(child: node);
    }

    return node;
  }

  static ({IconData icon, Color color, String label}) _stepConfig(_TimelineStep step) {
    return switch (step.type) {
      _TimelineStepType.thinking => (
        icon: Icons.psychology_rounded,
        color: const Color(0xFFF59E0B),
        label: 'Thinking',
      ),
      _TimelineStepType.toolCall => (
        icon: Icons.build_rounded,
        color: const Color(0xFF3B82F6),
        label: 'Tool call',
      ),
      _TimelineStepType.toolResult => (
        icon: Icons.inventory_2_rounded,
        color: const Color(0xFF10B981),
        label: 'Tool result',
      ),
      _TimelineStepType.compaction => (
        icon: Icons.compress_rounded,
        color: const Color(0xFFEC4899),
        label: 'Compaction',
      ),
      _TimelineStepType.text || _TimelineStepType.textActive => (
        icon: Icons.edit_note_rounded,
        color: const Color(0xFF8B5CF6),
        label: 'Response',
      ),
    };
  }
}

/// Simple pulsing animation wrapper for active timeline steps.
class _PulsingWidget extends StatefulWidget {
  final Widget child;
  const _PulsingWidget({required this.child});

  @override
  State<_PulsingWidget> createState() => _PulsingWidgetState();
}

class _PulsingWidgetState extends State<_PulsingWidget>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _opacity;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat(reverse: true);
    _opacity = Tween<double>(begin: 0.5, end: 1.0).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(opacity: _opacity, child: widget.child);
  }
}

// ── Regular Chat Bubble ───────────────────────────────────────────────────────

class _ChatBubble extends StatelessWidget {
  final Message message;
  final List<_PreAssistantItem> preItems;
  final List<_TimelineStep> timelineSteps;
  final bool isLoading;

  const _ChatBubble({
    required this.message,
    this.preItems = const [],
    this.timelineSteps = const [],
    this.isLoading = false,
  });

  @override
  Widget build(BuildContext context) {
    final isUser = message.isUser;
    final screenWidth = MediaQuery.of(context).size.width;
    final maxContentWidth = screenWidth > 900 ? 720.0 : screenWidth * 0.85;

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
      color: isUser ? Colors.transparent : Colors.white.withValues(alpha: 0.02),
      child: Center(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: maxContentWidth),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisAlignment: isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
            children: isUser
                ? [
                    Expanded(child: _buildContent(context, isUser)),
                    const SizedBox(width: 16),
                    _buildAvatar(isUser),
                  ]
                : [
                    _buildAvatar(isUser),
                    const SizedBox(width: 16),
                    Expanded(child: _buildContent(context, isUser)),
                  ],
          ),
        ),
      ),
    );
  }

  Widget _buildAvatar(bool isUser) {
    return Container(
      width: 32,
      height: 32,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(8),
        gradient: isUser
            ? const LinearGradient(colors: [Color(0xFF3B82F6), Color(0xFF2563EB)])
            : const LinearGradient(colors: [Color(0xFF8B5CF6), Color(0xFF6366F1)]),
      ),
      child: Icon(
        isUser ? Icons.person_rounded : Icons.auto_awesome,
        size: 16,
        color: Colors.white,
      ),
    );
  }

  Widget _buildContent(BuildContext context, bool isUser) {
    final isWide = MediaQuery.of(context).size.width > 768;
    final showTimeline = !isUser && timelineSteps.length > 1;
    final headerLabel = Text(
      (isUser ? 'You' : 'ThreadBot').toUpperCase(),
      style: TextStyle(
        fontSize: 10,
        fontWeight: FontWeight.w800,
        letterSpacing: 1.5,
        color: (isUser ? const Color(0xFF3B82F6) : const Color(0xFF8B5CF6))
            .withValues(alpha: 0.9),
      ),
    );

    return Column(
      crossAxisAlignment: isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
      children: [
        // Header + timeline: inline on wide, stacked on narrow
        if (showTimeline && isWide)
          Row(
            children: [
              headerLabel,
              const SizedBox(width: 12),
              Flexible(child: _ResponseTimeline(steps: timelineSteps)),
            ],
          )
        else if (showTimeline) ...[
          headerLabel,
          const SizedBox(height: 6),
          _ResponseTimeline(steps: timelineSteps),
        ] else
          headerLabel,
        // Render thinking blocks and tool call groups in chronological order
        if (!isUser && preItems.isNotEmpty) ...[
          const SizedBox(height: 8),
          ...preItems.map((item) {
            if (item.isThinking) {
              return _InlineThinkingBlock(message: item.thinking!);
            } else {
              return _InlineToolCallGroup(
                group: item.toolCallGroup!,
                isLoading: isLoading,
              );
            }
          }),
        ],
        const SizedBox(height: 6),
        _buildMessageBody(context, isUser),
      ],
    );
  }

  Widget _buildMessageBody(BuildContext context, bool isUser) {
    if (!isUser && message.content.isEmpty) {
      return const Padding(
        padding: EdgeInsets.only(top: 8),
        child: _TypingDots(),
      );
    }

    final style = MarkdownStyleSheet(
      p: const TextStyle(
        fontSize: 15,
        height: 1.6,
        color: Color(0xFFD4D4D8),
      ),
      h1: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold, color: Color(0xFFE4E4E7)),
      h2: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold, color: Color(0xFFE4E4E7)),
      h3: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600, color: Color(0xFFE4E4E7)),
      strong: const TextStyle(fontWeight: FontWeight.w600, color: Color(0xFFE4E4E7)),
      em: const TextStyle(fontStyle: FontStyle.italic),
      code: TextStyle(
        backgroundColor: Colors.white.withValues(alpha: 0.06),
        fontSize: 13,
        fontFamily: 'monospace',
        color: const Color(0xFFA78BFA),
      ),
      codeblockDecoration: BoxDecoration(
        color: const Color(0xFF111118),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
      ),
      codeblockPadding: const EdgeInsets.all(16),
      blockSpacing: 12,
      listBullet: const TextStyle(color: Color(0xFF8B5CF6)),
      blockquoteDecoration: BoxDecoration(
        border: Border(
          left: BorderSide(
            color: const Color(0xFF8B5CF6).withValues(alpha: 0.5),
            width: 3,
          ),
        ),
      ),
      blockquotePadding: const EdgeInsets.only(left: 16, top: 4, bottom: 4),
    );

    if (!isUser && message.id.startsWith('temp-ast-')) {
      return _AnimatedMarkdown(data: message.content, styleSheet: style);
    }

    return MarkdownBody(
      data: message.content,
      selectable: true,
      onTapLink: (text, href, title) {
        if (href != null) launchUrl(Uri.parse(href));
      },
      styleSheet: style,
    );
  }
}

/// Renders a tool_call group inline within an assistant bubble.
class _InlineToolCallGroup extends StatelessWidget {
  final _ToolCallGroup group;
  final bool isLoading;
  const _InlineToolCallGroup({required this.group, this.isLoading = false});

  static List<String> _parseToolCalls(String content) {
    var body = content;
    if (body.startsWith('Calling ')) {
      body = body.substring('Calling '.length);
    }
    return body.split(',').map((s) => s.trim()).where((s) => s.isNotEmpty).toList();
  }

  static bool _isError(String content) {
    if (content.startsWith('Error executing tool:') ||
        content.startsWith('Error:') ||
        content == 'Tool not found') {
      return true;
    }
    try {
      final parsed = jsonDecode(content);
      if (parsed is Map && parsed.containsKey('error')) return true;
    } catch (_) {}
    return false;
  }

  @override
  Widget build(BuildContext context) {
    final tools = _parseToolCalls(group.message.content);
    final toolCalls = group.message.metadata?['tool_calls'] as List<dynamic>?;

    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: List.generate(tools.length, (i) {
          final result = i < group.results.length ? group.results[i] : null;
          final succeeded = result != null && !_isError(result.content);
          final failed = result != null && _isError(result.content);
          final chipLoading = isLoading && result == null;

          String? toolInput;
          if (toolCalls != null && i < toolCalls.length) {
            final tc = toolCalls[i] as Map<String, dynamic>?;
            final fn = tc?['function'] as Map<String, dynamic>?;
            toolInput = fn?['arguments'] as String?;
          }

          return _ToolCallChip(
            tool: tools[i],
            isLoading: chipLoading,
            succeeded: succeeded,
            failed: failed,
            result: result,
            toolInput: toolInput,
          );
        }),
      ),
    );
  }
}

class _AnimatedMarkdown extends StatefulWidget {
  final String data;
  final MarkdownStyleSheet styleSheet;

  const _AnimatedMarkdown({
    required this.data,
    required this.styleSheet,
  });

  @override
  State<_AnimatedMarkdown> createState() => _AnimatedMarkdownState();
}

class _AnimatedMarkdownState extends State<_AnimatedMarkdown> with SingleTickerProviderStateMixin {
  late String _currentData;

  @override
  void initState() {
    super.initState();
    _currentData = widget.data;
  }

  @override
  void didUpdateWidget(_AnimatedMarkdown oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.data != oldWidget.data) {
      setState(() {
        _currentData = widget.data;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return MarkdownBody(
      data: _currentData,
      styleSheet: widget.styleSheet,
    );
  }
}

class _TypingDots extends StatefulWidget {
  const _TypingDots();

  @override
  State<_TypingDots> createState() => _TypingDotsState();
}

class _TypingDotsState extends State<_TypingDots> with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _shimmer;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1800),
    )..repeat();
    _shimmer = CurvedAnimation(parent: _controller, curve: Curves.easeInOut);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _shimmer,
      builder: (context, _) {
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Paragraph-like skeleton — varies widths to mimic real text
            _buildBar(widthFraction: 1.0,  delay: 0.0),
            const SizedBox(height: 8),
            _buildBar(widthFraction: 0.92, delay: 0.06),
            const SizedBox(height: 8),
            _buildBar(widthFraction: 0.97, delay: 0.12),
            const SizedBox(height: 8),
            _buildBar(widthFraction: 0.85, delay: 0.18),
            const SizedBox(height: 8),
            _buildBar(widthFraction: 0.55, delay: 0.24),
          ],
        );
      },
    );
  }

  Widget _buildBar({required double widthFraction, required double delay}) {
    // Offset the shimmer phase per bar for a cascading effect
    final t = (_shimmer.value + delay) % 1.0;
    final opacity = 0.15 + 0.25 * (0.5 + 0.5 * (1.0 - (2.0 * t - 1.0).abs()));

    return FractionallySizedBox(
      alignment: Alignment.centerLeft,
      widthFactor: widthFraction,
      child: Container(
        height: 14,
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(4),
          gradient: LinearGradient(
            colors: [
              const Color(0xFF8B5CF6).withValues(alpha: opacity * 0.5),
              const Color(0xFF6366F1).withValues(alpha: opacity),
              const Color(0xFF8B5CF6).withValues(alpha: opacity * 0.5),
            ],
            stops: [
              (t - 0.3).clamp(0.0, 1.0),
              t,
              (t + 0.3).clamp(0.0, 1.0),
            ],
          ),
        ),
      ),
    );
  }
}
