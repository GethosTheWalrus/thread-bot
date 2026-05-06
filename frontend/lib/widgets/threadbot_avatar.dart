import 'package:flutter/material.dart';

class ThreadbotAvatar extends StatelessWidget {
  final double size;
  final double borderRadius;
  final bool showNeedle;
  final bool showShadow;
  final bool showBackground;

  const ThreadbotAvatar({
    super.key,
    this.size = 44, // Reasonable default
    this.borderRadius = 10,
    this.showNeedle = true,
    this.showShadow = true,
    this.showBackground = true,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size,
      height: size,
      child: Stack(
        clipBehavior: Clip.none, // Never cut off the 3D mascot
        alignment: Alignment.center,
        children: [
          // Centered Glow Effect (behind everything)
          if (showShadow)
            Container(
              width: size * 0.6,
              height: size * 0.6,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: const Color(0xFF8B5CF6).withValues(alpha: 0.35),
                    blurRadius: size / 2.5,
                    spreadRadius: 2,
                  ),
                ],
              ),
            ),
          
          // Background Box (optional)
          if (showBackground)
            Container(
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(borderRadius),
                color: const Color(0xFF111118),
              ),
            ),

          // 3D Mascot View
          if (showBackground)
            ClipRRect(
              borderRadius: BorderRadius.circular(borderRadius),
              child: _build3DView(),
            )
          else
            _build3DView(),
        ],
      ),
    );
  }

  Widget _build3DView() {
    return HtmlElementView(
      key: ValueKey('bot-avatar-${size.toInt()}-${showNeedle ? "needle" : "none"}-${showShadow ? "shadow" : "none"}-${showBackground ? "bg" : "none"}'),
      viewType: showNeedle ? 'poly-bot-view' : 'poly-bot-view-no-needle',
    );
  }
}
