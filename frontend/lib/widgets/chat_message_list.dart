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
    return ListView.builder(
      controller: scrollController,
      padding: const EdgeInsets.symmetric(vertical: 24),
      itemCount: messages.length,
      itemBuilder: (context, index) {
        final msg = messages[index];
        if (msg.isCompactionSummary) return _CompactionDivider(message: msg);
        if (msg.isToolCall) return _ToolCallBubble(message: msg);
        if (msg.isToolResult) return _ToolResultBubble(message: msg);
        if (msg.isSystem) return const SizedBox.shrink(); // hide other system messages
        return _ChatBubble(message: msg);
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
    final count = message.metadata?['original_message_count'];
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

class _ToolCallBubble extends StatelessWidget {
  final Message message;
  const _ToolCallBubble({required this.message});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 4),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: Row(
            children: [
              const SizedBox(width: 48), // align with assistant messages
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(8),
                  color: const Color(0xFF8B5CF6).withValues(alpha: 0.08),
                  border: Border.all(color: const Color(0xFF8B5CF6).withValues(alpha: 0.2)),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.build_outlined, size: 14, color: Color(0xFF8B5CF6)),
                    const SizedBox(width: 8),
                    Text(
                      message.content,
                      style: const TextStyle(
                        fontSize: 12,
                        color: Color(0xFF8B5CF6),
                        fontStyle: FontStyle.italic,
                      ),
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

// ── Tool Result Bubble ────────────────────────────────────────────────────────

class _ToolResultBubble extends StatefulWidget {
  final Message message;
  const _ToolResultBubble({required this.message});

  @override
  State<_ToolResultBubble> createState() => _ToolResultBubbleState();
}

class _ToolResultBubbleState extends State<_ToolResultBubble> {
  bool _expanded = false;

  static const int _previewLength = 200;

  @override
  Widget build(BuildContext context) {
    final content = widget.message.content;
    final toolName = widget.message.metadata?['tool_name'] as String? ?? 'Tool';
    final isLong = content.length > _previewLength;
    final displayText = _expanded || !isLong ? content : '${content.substring(0, _previewLength)}...';

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
                child: Container(
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(8),
                    color: const Color(0xFF111118),
                    border: Border.all(color: Colors.white.withValues(alpha: 0.06)),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // Header bar
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                        decoration: BoxDecoration(
                          borderRadius: const BorderRadius.vertical(top: Radius.circular(8)),
                          color: Colors.white.withValues(alpha: 0.03),
                          border: Border(
                            bottom: BorderSide(color: Colors.white.withValues(alpha: 0.06)),
                          ),
                        ),
                        child: Row(
                          children: [
                            const Icon(Icons.terminal_rounded, size: 12, color: Color(0xFF71717A)),
                            const SizedBox(width: 6),
                            Text(
                              toolName,
                              style: const TextStyle(fontSize: 11, color: Color(0xFF71717A)),
                            ),
                            const Spacer(),
                            if (isLong)
                              GestureDetector(
                                onTap: () => setState(() => _expanded = !_expanded),
                                child: Text(
                                  _expanded ? 'Collapse' : 'Expand',
                                  style: const TextStyle(
                                    fontSize: 11,
                                    color: Color(0xFF8B5CF6),
                                    fontWeight: FontWeight.w500,
                                  ),
                                ),
                              ),
                          ],
                        ),
                      ),
                      // Content
                      Padding(
                        padding: const EdgeInsets.all(12),
                        child: SelectableText(
                          displayText,
                          style: const TextStyle(
                            fontSize: 12,
                            fontFamily: 'monospace',
                            color: Color(0xFFA1A1AA),
                            height: 1.5,
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

// ── Regular Chat Bubble ───────────────────────────────────────────────────────

class _ChatBubble extends StatelessWidget {
  final Message message;

  const _ChatBubble({required this.message});

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
    return Column(
      crossAxisAlignment: isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
      children: [
        Text(
          (isUser ? 'You' : 'ThreadBot').toUpperCase(),
          style: TextStyle(
            fontSize: 10,
            fontWeight: FontWeight.w800,
            letterSpacing: 1.5,
            color: (isUser ? const Color(0xFF3B82F6) : const Color(0xFF8B5CF6))
                .withValues(alpha: 0.9),
          ),
        ),
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

class _TypingDotsState extends State<_TypingDots> with TickerProviderStateMixin {
  late final List<AnimationController> _controllers;
  late final List<Animation<double>> _animations;

  @override
  void initState() {
    super.initState();
    _controllers = List.generate(3, (i) {
      final controller = AnimationController(
        vsync: this,
        duration: const Duration(milliseconds: 600),
      );
      Future.delayed(Duration(milliseconds: i * 200), () {
        if (mounted) controller.repeat(reverse: true);
      });
      return controller;
    });
    _animations = _controllers
        .map((c) => Tween<double>(begin: 0.3, end: 1.0).animate(
              CurvedAnimation(parent: c, curve: Curves.easeInOut),
            ))
        .toList();
  }

  @override
  void dispose() {
    for (final c in _controllers) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Row(
      children: List.generate(3, (i) {
        return AnimatedBuilder(
          animation: _animations[i],
          builder: (_, __) => Container(
            width: 8,
            height: 8,
            margin: const EdgeInsets.only(right: 4),
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: Color.lerp(
                const Color(0xFF3F3F46),
                const Color(0xFF8B5CF6),
                _animations[i].value,
              ),
            ),
          ),
        );
      }),
    );
  }
}
