import 'dart:math' as math;
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:threadbot/services/api_service.dart';
import 'package:threadbot/utils/web_image_io.dart';

class ChatInput extends StatefulWidget {
  final Future<void> Function(String content, List<String> imageUrls) onSend;
  final bool isSending;
  final VoidCallback? onToolsPressed;
  final bool hasToolOverrides;
  final VoidCallback? onLlmOverridesPressed;
  final bool hasLlmOverrides;
  final bool hasThread;
  final int estimatedTokens;
  final int contextWindow;

  const ChatInput({
    super.key,
    required this.onSend,
    this.isSending = false,
    this.onToolsPressed,
    this.hasToolOverrides = false,
    this.onLlmOverridesPressed,
    this.hasLlmOverrides = false,
    this.hasThread = false,
    this.estimatedTokens = 0,
    this.contextWindow = 8192,
  });

  @override
  State<ChatInput> createState() => _ChatInputState();
}

class _ChatInputState extends State<ChatInput> {
  final TextEditingController _controller = TextEditingController();
  final FocusNode _focusNode = FocusNode();
  final ApiService _api = ApiService();
  final List<_AttachedImage> _attachments = [];
  bool _hasText = false;
  bool _isUploadingImages = false;
  StreamSubscription? _pasteSubscription;

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
    _pasteSubscription = listenForImagePaste(_handlePastedImages);
  }

  @override
  void dispose() {
    _pasteSubscription?.cancel();
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  bool get _canSend =>
      (_hasText || _attachments.isNotEmpty) &&
      !widget.isSending &&
      !_isUploadingImages;

  Future<void> _handlePastedImages(List<WebImageFile> files) async {
    if (files.isEmpty || !mounted) return;
    await _uploadImages(files);
  }

  Future<void> _pickImages() async {
    if (_isUploadingImages || widget.isSending) return;
    try {
      final files = await pickImageFiles(multiple: true);
      if (!mounted || files.isEmpty) return;
      await _uploadImages(files);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Failed to add image: $e'),
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

  Future<void> _uploadImages(List<WebImageFile> files) async {
    if (files.isEmpty) return;
    setState(() => _isUploadingImages = true);
    try {
      final urls = await _api.uploadImages(files);
      if (!mounted || urls.isEmpty) return;
      setState(() {
        _attachments.addAll(urls.map((url) => _AttachedImage(url: url)));
      });
      _focusNode.requestFocus();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Image upload failed: $e'),
            backgroundColor: Colors.red.shade800,
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(10),
            ),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _isUploadingImages = false);
    }
  }

  void _removeAttachment(int index) {
    setState(() {
      _attachments.removeAt(index);
    });
  }

  Future<void> _handleSend() async {
    final text = _controller.text.trim();
    if ((text.isEmpty && _attachments.isEmpty) || !_canSend) return;

    final imageUrls = _attachments
        .map((attachment) => attachment.url)
        .toList(growable: false);
    setState(() {
      _attachments.clear();
      _hasText = false;
    });
    _controller.clear();
    await widget.onSend(text, imageUrls);
    if (!mounted) return;
    _focusNode.requestFocus();
  }

  void _showThreadControls(BuildContext sourceContext) {
    showModalBottomSheet<void>(
      context: sourceContext,
      isScrollControlled: true,
      backgroundColor: const Color(0xFF16161E),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (sheetContext) => SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 640),
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
                        color: Colors.white24,
                        borderRadius: BorderRadius.circular(3),
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  const Text(
                    'Thread Controls',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 8),
                  _ControlsRow(
                    icon: Icons.data_usage_rounded,
                    title: 'Context usage',
                    subtitle: _contextSummary,
                  ),
                  _ControlsRow(
                    icon: Icons.tune_rounded,
                    title: 'Response settings',
                    subtitle: widget.hasThread
                        ? (widget.hasLlmOverrides ? 'Custom' : 'Default')
                        : 'Available after this thread is created',
                    enabled:
                        widget.hasThread &&
                        widget.onLlmOverridesPressed != null,
                    onTap: () {
                      Navigator.pop(sheetContext);
                      WidgetsBinding.instance.addPostFrameCallback(
                        (_) => widget.onLlmOverridesPressed?.call(),
                      );
                    },
                  ),
                  _ControlsRow(
                    icon: Icons.build_outlined,
                    title: 'MCP tools',
                    subtitle: widget.hasToolOverrides
                        ? 'Customized'
                        : 'All enabled',
                    enabled: widget.onToolsPressed != null,
                    onTap: () {
                      Navigator.pop(sheetContext);
                      WidgetsBinding.instance.addPostFrameCallback(
                        (_) => widget.onToolsPressed?.call(),
                      );
                    },
                  ),
                  if (!widget.hasThread)
                    Padding(
                      padding: const EdgeInsets.only(
                        left: 52,
                        top: 0,
                        bottom: 4,
                      ),
                      child: Text(
                        'Response settings apply to an existing thread. MCP tool choices can be prepared now.',
                        style: TextStyle(
                          fontSize: 12,
                          color: Colors.white.withValues(alpha: 0.45),
                        ),
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

  String get _contextSummary {
    if (widget.estimatedTokens <= 0) return 'No usage reported yet';
    final percent = widget.contextWindow > 0
        ? (widget.estimatedTokens / widget.contextWindow * 100).round()
        : 0;
    return '${widget.estimatedTokens} / ${widget.contextWindow} tokens ($percent%)';
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
              if (_attachments.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: Wrap(
                      spacing: 10,
                      runSpacing: 10,
                      children: List.generate(_attachments.length, (index) {
                        final attachment = _attachments[index];
                        final resolved = Uri.base
                            .resolve(attachment.url)
                            .toString();
                        final filename = Uri.parse(
                          attachment.url,
                        ).pathSegments.last;
                        return Stack(
                          clipBehavior: Clip.none,
                          children: [
                            Container(
                              width: 84,
                              height: 84,
                              decoration: BoxDecoration(
                                borderRadius: BorderRadius.circular(14),
                                color: const Color(0xFF111118),
                                border: Border.all(
                                  color: Colors.white.withValues(alpha: 0.08),
                                ),
                              ),
                              clipBehavior: Clip.antiAlias,
                              child: Stack(
                                children: [
                                  Positioned.fill(
                                    child: Image.network(
                                      resolved,
                                      fit: BoxFit.cover,
                                      errorBuilder: (_, __, ___) => Center(
                                        child: Padding(
                                          padding: const EdgeInsets.all(8),
                                          child: Text(
                                            filename,
                                            maxLines: 3,
                                            overflow: TextOverflow.ellipsis,
                                            textAlign: TextAlign.center,
                                            style: TextStyle(
                                              fontSize: 11,
                                              color: Colors.white.withValues(
                                                alpha: 0.55,
                                              ),
                                            ),
                                          ),
                                        ),
                                      ),
                                    ),
                                  ),
                                  Positioned(
                                    left: 6,
                                    right: 6,
                                    bottom: 6,
                                    child: Container(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 6,
                                        vertical: 3,
                                      ),
                                      decoration: BoxDecoration(
                                        color: Colors.black.withValues(
                                          alpha: 0.55,
                                        ),
                                        borderRadius: BorderRadius.circular(6),
                                      ),
                                      child: Text(
                                        filename,
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis,
                                        style: const TextStyle(
                                          fontSize: 10,
                                          color: Colors.white,
                                        ),
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            Positioned(
                              top: -6,
                              right: -6,
                              child: Material(
                                color: Colors.transparent,
                                child: InkWell(
                                  borderRadius: BorderRadius.circular(999),
                                  onTap: () => _removeAttachment(index),
                                  child: Container(
                                    width: 22,
                                    height: 22,
                                    decoration: BoxDecoration(
                                      color: const Color(0xFF111118),
                                      shape: BoxShape.circle,
                                      border: Border.all(
                                        color: Colors.white.withValues(
                                          alpha: 0.08,
                                        ),
                                      ),
                                    ),
                                    child: Semantics(
                                      label: 'Remove attachment',
                                      button: true,
                                      child: const Icon(
                                        Icons.close_rounded,
                                        size: 14,
                                        color: Colors.white70,
                                      ),
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          ],
                        );
                      }),
                    ),
                  ),
                ),
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
                    Expanded(
                      child: Stack(
                        children: [
                          if (!_hasText)
                            Positioned(
                              left: 20,
                              top: 14,
                              child: IgnorePointer(
                                child: Text(
                                  _attachments.isEmpty
                                      ? 'Message ThreadBot...'
                                      : 'Add a note...',
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
                                contentPadding: EdgeInsets.fromLTRB(
                                  20,
                                  14,
                                  8,
                                  14,
                                ),
                                filled: false,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: IconButton(
                        tooltip: 'Attach images',
                        onPressed:
                            kIsWeb && !_isUploadingImages && !widget.isSending
                            ? _pickImages
                            : null,
                        icon: _isUploadingImages
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : Icon(
                                Icons.add_photo_alternate_outlined,
                                size: 16,
                                color: Colors.white.withValues(alpha: 0.3),
                              ),
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: _ThreadControlsButton(
                        hasOverrides:
                            widget.hasLlmOverrides || widget.hasToolOverrides,
                        estimatedTokens: widget.estimatedTokens,
                        contextWindow: widget.contextWindow,
                        onPressed: () => _showThreadControls(context),
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.only(right: 8, bottom: 6),
                      child: IconButton(
                        tooltip: 'Send message',
                        onPressed: _canSend ? _handleSend : null,
                        icon: widget.isSending
                            ? const SizedBox(
                                width: 16,
                                height: 16,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : Icon(
                                Icons.arrow_upward_rounded,
                                color: _canSend
                                    ? Colors.white
                                    : Colors.white.withValues(alpha: 0.2),
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

class _AttachedImage {
  final String url;

  const _AttachedImage({required this.url});
}

class _ControlsRow extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final bool enabled;
  final VoidCallback? onTap;

  const _ControlsRow({
    required this.icon,
    required this.title,
    required this.subtitle,
    this.enabled = true,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) => Semantics(
    button: onTap != null,
    enabled: enabled,
    label: '$title, $subtitle',
    child: ListTile(
      enabled: enabled,
      minVerticalPadding: 8,
      leading: Icon(
        icon,
        color: enabled ? const Color(0xFF8B5CF6) : Colors.white24,
      ),
      title: Text(title),
      subtitle: Text(subtitle),
      trailing: onTap == null ? null : const Icon(Icons.chevron_right_rounded),
      onTap: enabled ? onTap : null,
    ),
  );
}

class _ThreadControlsButton extends StatelessWidget {
  final bool hasOverrides;
  final int estimatedTokens;
  final int contextWindow;
  final VoidCallback onPressed;

  const _ThreadControlsButton({
    required this.hasOverrides,
    required this.estimatedTokens,
    required this.contextWindow,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    final ratio = contextWindow > 0
        ? (estimatedTokens / contextWindow).clamp(0.0, 1.0)
        : 0.0;
    return Tooltip(
      message: 'Thread controls',
      child: Semantics(
        label:
            'Thread controls${hasOverrides ? ', custom settings active' : ''}',
        button: true,
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: onPressed,
          child: SizedBox(
            width: 40,
            height: 40,
            child: Stack(
              alignment: Alignment.center,
              children: [
                if (estimatedTokens > 0)
                  CustomPaint(
                    size: const Size(28, 28),
                    painter: _DonutPainter(
                      ratio: ratio,
                      arcColor: ratio > .75
                          ? Colors.redAccent
                          : ratio > .5
                          ? Colors.amber
                          : Colors.greenAccent,
                    ),
                  ),
                Icon(
                  Icons.tune_rounded,
                  size: 17,
                  color: hasOverrides
                      ? const Color(0xFF8B5CF6)
                      : Colors.white54,
                ),
                if (hasOverrides)
                  Positioned(
                    right: 5,
                    top: 5,
                    child: Container(
                      width: 6,
                      height: 6,
                      decoration: const BoxDecoration(
                        color: Color(0xFF8B5CF6),
                        shape: BoxShape.circle,
                      ),
                    ),
                  ),
              ],
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
