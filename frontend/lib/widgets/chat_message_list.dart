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
      itemCount: messages.length + (isSending ? 1 : 0),
      itemBuilder: (context, index) {
        if (index == messages.length && isSending) {
          return _buildTypingIndicator();
        }
        return _ChatBubble(message: messages[index]);
      },
    );
  }

  Widget _buildTypingIndicator() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _buildAvatar(false),
          const SizedBox(width: 16),
          Expanded(
            child: Container(
              constraints: const BoxConstraints(maxWidth: 720),
              child: const _TypingDots(),
            ),
          ),
          const SizedBox(width: 56),
        ],
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
}

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
            children: [
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
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          isUser ? 'You' : 'ThreadBot',
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w600,
            color: Colors.white.withValues(alpha: 0.7),
          ),
        ),
        const SizedBox(height: 6),
        MarkdownBody(
          data: message.content,
          selectable: true,
          onTapLink: (text, href, title) {
            if (href != null) launchUrl(Uri.parse(href));
          },
          styleSheet: MarkdownStyleSheet(
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
          ),
        ),
      ],
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
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'ThreadBot',
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w600,
            color: Colors.white.withValues(alpha: 0.7),
          ),
        ),
        const SizedBox(height: 8),
        Row(
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
        ),
      ],
    );
  }
}
