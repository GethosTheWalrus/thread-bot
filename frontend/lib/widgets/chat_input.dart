import 'package:flutter/material.dart';
import 'dart:math' as math;

class ChatInput extends StatefulWidget {
  final Function(String) onSend;
  final bool isSending;
  final VoidCallback? onToolsPressed;
  final bool hasToolOverrides;
  final int estimatedTokens;
  final int contextWindow;

  const ChatInput({
    super.key,
    required this.onSend,
    this.isSending = false,
    this.onToolsPressed,
    this.hasToolOverrides = false,
    this.estimatedTokens = 0,
    this.contextWindow = 8192,
  });

  @override
  State<ChatInput> createState() => _ChatInputState();
}

class _ChatInputState extends State<ChatInput> {
  final TextEditingController _controller = TextEditingController();
  final FocusNode _focusNode = FocusNode();
  bool _hasText = false;

  @override
  void initState() {
    super.initState();
    _controller.addListener(() {
      final hasText = _controller.text.trim().isNotEmpty;
      if (hasText != _hasText) {
        setState(() => _hasText = hasText);
      }
    });
    _focusNode.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  void _handleSend() {
    final text = _controller.text.trim();
    if (text.isEmpty || widget.isSending) return;

    widget.onSend(text);
    _controller.clear();
    _focusNode.requestFocus();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(24, 12, 24, 24),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 768),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(20),
                  color: const Color(0xFF16161E),
                  border: Border.all(
                    color: _focusNode.hasFocus
                        ? const Color(0xFF8B5CF6).withValues(alpha: 0.4)
                        : Colors.white.withValues(alpha: 0.08),
                  ),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: 0.3),
                      blurRadius: 20,
                      offset: const Offset(0, 4),
                    ),
                  ],
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    // Text field with stack-based hint to avoid native placeholder doubling
                    Expanded(
                      child: Stack(
                        children: [
                          // Hint overlay (avoids browser native placeholder)
                          if (!_hasText)
                            Positioned(
                              left: 20,
                              top: 14,
                              child: IgnorePointer(
                                child: Text(
                                  'Message ThreadBot...',
                                  style: TextStyle(
                                    fontSize: 15,
                                    height: 1.5,
                                    color: Colors.white.withValues(alpha: 0.25),
                                  ),
                                ),
                              ),
                            ),
                          TextSelectionTheme(
                            data: const TextSelectionThemeData(
                              selectionColor: Color(0x408B5CF6),
                            ),
                            child: TextField(
                              controller: _controller,
                              focusNode: _focusNode,
                              maxLines: 6,
                              minLines: 1,
                              textInputAction: TextInputAction.send,
                              onSubmitted: (_) => _handleSend(),
                              cursorColor: const Color(0xFF8B5CF6),
                              enableSuggestions: false,
                              autocorrect: false,
                              style: const TextStyle(
                                fontSize: 15,
                                color: Color(0xFFE4E4E7),
                                height: 1.5,
                              ),
                              decoration: const InputDecoration(
                                border: InputBorder.none,
                                contentPadding: EdgeInsets.fromLTRB(20, 14, 8, 14),
                                filled: false,
                                // No hintText — using Stack overlay instead
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),

                    // Context donut
                    if (widget.estimatedTokens > 0)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 6),
                        child: _ContextDonut(
                          estimatedTokens: widget.estimatedTokens,
                          contextWindow: widget.contextWindow,
                        ),
                      ),

                    // Tools button
                    if (widget.onToolsPressed != null)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 6),
                        child: Material(
                          color: Colors.transparent,
                          child: InkWell(
                            borderRadius: BorderRadius.circular(12),
                            onTap: widget.onToolsPressed,
                            child: Container(
                              width: 36,
                              height: 36,
                              decoration: BoxDecoration(
                                borderRadius: BorderRadius.circular(12),
                                color: widget.hasToolOverrides
                                    ? const Color(0xFF8B5CF6).withValues(alpha: 0.15)
                                    : Colors.transparent,
                              ),
                              child: Icon(
                                Icons.build_outlined,
                                size: 16,
                                color: widget.hasToolOverrides
                                    ? const Color(0xFF8B5CF6)
                                    : Colors.white.withValues(alpha: 0.3),
                              ),
                            ),
                          ),
                        ),
                      ),

                    // Send button
                    Padding(
                      padding: const EdgeInsets.only(right: 8, bottom: 6),
                      child: AnimatedScale(
                        scale: _hasText && !widget.isSending ? 1.0 : 0.85,
                        duration: const Duration(milliseconds: 150),
                        child: Material(
                          color: Colors.transparent,
                          child: InkWell(
                            borderRadius: BorderRadius.circular(12),
                            onTap: _hasText && !widget.isSending ? _handleSend : null,
                            child: Container(
                              width: 36,
                              height: 36,
                              decoration: BoxDecoration(
                                borderRadius: BorderRadius.circular(12),
                                color: _hasText && !widget.isSending
                                    ? const Color(0xFF8B5CF6)
                                    : Colors.white.withValues(alpha: 0.06),
                              ),
                              child: widget.isSending
                                  ? const Padding(
                                      padding: EdgeInsets.all(10),
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2,
                                        valueColor: AlwaysStoppedAnimation(Colors.white),
                                      ),
                                    )
                                  : Icon(
                                      Icons.arrow_upward_rounded,
                                      size: 18,
                                      color: _hasText
                                          ? Colors.white
                                          : Colors.white.withValues(alpha: 0.2),
                                    ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 8),
              Text(
                'ThreadBot can make mistakes. Powered by Temporal workflows.',
                style: TextStyle(
                  fontSize: 11,
                  color: Colors.white.withValues(alpha: 0.2),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}


/// Small donut chart showing context window consumption.
class _ContextDonut extends StatelessWidget {
  final int estimatedTokens;
  final int contextWindow;

  const _ContextDonut({
    required this.estimatedTokens,
    required this.contextWindow,
  });

  @override
  Widget build(BuildContext context) {
    final ratio = contextWindow > 0
        ? (estimatedTokens / contextWindow).clamp(0.0, 1.0)
        : 0.0;
    final percentage = (ratio * 100).round();

    // Color shifts: green → amber → red
    final Color arcColor;
    if (ratio < 0.5) {
      arcColor = const Color(0xFF10B981); // green
    } else if (ratio < 0.75) {
      arcColor = const Color(0xFFF59E0B); // amber
    } else {
      arcColor = const Color(0xFFEF4444); // red
    }

    final tokenLabel = estimatedTokens >= 1000
        ? '${(estimatedTokens / 1000).toStringAsFixed(1)}k'
        : '$estimatedTokens';
    final windowLabel = contextWindow >= 1000
        ? '${(contextWindow / 1000).toStringAsFixed(0)}k'
        : '$contextWindow';

    return Tooltip(
      message: '$tokenLabel / $windowLabel tokens ($percentage%)',
      child: SizedBox(
        width: 36,
        height: 36,
        child: CustomPaint(
          painter: _DonutPainter(
            ratio: ratio,
            arcColor: arcColor,
          ),
          child: Center(
            child: Text(
              '$percentage%',
              style: TextStyle(
                fontSize: 8,
                fontWeight: FontWeight.w600,
                color: Colors.white.withValues(alpha: 0.5),
              ),
            ),
          ),
        ),
      ),
    );
  }
}


class _DonutPainter extends CustomPainter {
  final double ratio;
  final Color arcColor;

  _DonutPainter({required this.ratio, required this.arcColor});

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = size.width / 2 - 4;
    const strokeWidth = 3.0;

    // Background track
    final bgPaint = Paint()
      ..color = Colors.white.withValues(alpha: 0.08)
      ..style = PaintingStyle.stroke
      ..strokeWidth = strokeWidth
      ..strokeCap = StrokeCap.round;

    canvas.drawCircle(center, radius, bgPaint);

    // Filled arc
    if (ratio > 0) {
      final arcPaint = Paint()
        ..color = arcColor
        ..style = PaintingStyle.stroke
        ..strokeWidth = strokeWidth
        ..strokeCap = StrokeCap.round;

      final sweepAngle = 2 * math.pi * ratio;
      canvas.drawArc(
        Rect.fromCircle(center: center, radius: radius),
        -math.pi / 2, // start from top
        sweepAngle,
        false,
        arcPaint,
      );
    }
  }

  @override
  bool shouldRepaint(_DonutPainter oldDelegate) =>
      oldDelegate.ratio != ratio || oldDelegate.arcColor != arcColor;
}
