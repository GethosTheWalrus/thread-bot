import 'dart:math' as math;
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:threadbot/services/api_service.dart';
import 'package:threadbot/utils/web_image_io.dart';
import 'package:threadbot/models/thread.dart';

String? mentionQueryAtCaret(String text, int caret) {
  if (caret < 0 || caret > text.length) return null;
  final before = text.substring(0, caret);
  return RegExp(
    r'(?<!\\)(?:^|\s)@([A-Za-z0-9_-]*)$',
  ).firstMatch(before)?.group(1);
}

class ChatInput extends StatefulWidget {
  final Future<void> Function(String content, List<String> imageUrls) onSend;
  final bool isSending;
  final VoidCallback? onThreadControlsPressed;
  final bool hasToolOverrides;
  final bool hasLlmOverrides;
  final int estimatedTokens;
  final int contextWindow;
  final List<ThreadAgentSummary> participants;

  const ChatInput({
    super.key,
    required this.onSend,
    this.isSending = false,
    this.onThreadControlsPressed,
    this.hasToolOverrides = false,
    this.hasLlmOverrides = false,
    this.estimatedTokens = 0,
    this.contextWindow = 8192,
    this.participants = const [],
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
  String? _mentionQuery;
  StreamSubscription? _pasteSubscription;

  @override
  void initState() {
    super.initState();
    _controller.addListener(() {
      final hasText = _controller.text.trim().isNotEmpty;
      if (hasText != _hasText) {
        setState(() => _hasText = hasText);
      }
      final query = mentionQueryAtCaret(
        _controller.text,
        _controller.selection.baseOffset,
      );
      if (query != _mentionQuery) setState(() => _mentionQuery = query);
    });
    _focusNode.addListener(() => setState(() {}));
    _pasteSubscription = listenForImagePaste(_handlePastedImages);
  }

  List<ThreadAgentSummary> get _mentionSuggestions {
    final query = (_mentionQuery ?? '').toLowerCase();
    return widget.participants
        .where(
          (agent) =>
              !agent.isSystem &&
              agent.mentionName.isNotEmpty &&
              agent.status.toLowerCase() != 'archived' &&
              agent.mentionName.toLowerCase().startsWith(query),
        )
        .take(6)
        .toList();
  }

  void _insertMention(ThreadAgentSummary agent) {
    final caret = _controller.selection.baseOffset;
    final before = _controller.text.substring(0, caret);
    final match = RegExp(r'(?<!\\)(?:^|\s)@[A-Za-z0-9_-]*$').firstMatch(before);
    if (match == null) return;
    final start = match.start + (before[match.start] == '@' ? 0 : 1);
    final replacement = '@${agent.mentionName} ';
    _controller.value = TextEditingValue(
      text: _controller.text.replaceRange(start, caret, replacement),
      selection: TextSelection.collapsed(offset: start + replacement.length),
    );
    _focusNode.requestFocus();
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

  Widget _buildThreadControls(BuildContext context) {
    return _ThreadControlsButton(
      hasOverrides: widget.hasLlmOverrides || widget.hasToolOverrides,
      onPressed: widget.onThreadControlsPressed ?? () {},
    );
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
                          if (_mentionSuggestions.isNotEmpty)
                            Positioned(
                              left: 12,
                              right: 12,
                              bottom: 58,
                              child: Material(
                                color: const Color(0xFF24232E),
                                borderRadius: BorderRadius.circular(14),
                                elevation: 10,
                                child: Column(
                                  mainAxisSize: MainAxisSize.min,
                                  children: _mentionSuggestions
                                      .map(
                                        (agent) => ListTile(
                                          dense: true,
                                          leading: CircleAvatar(
                                            radius: 14,
                                            child: Text(
                                              agent.name.isEmpty
                                                  ? '?'
                                                  : agent.name[0].toUpperCase(),
                                            ),
                                          ),
                                          title: Text(agent.name),
                                          subtitle: Text(
                                            '@${agent.mentionName} · ${agent.status}',
                                          ),
                                          trailing: agent.isModerator
                                              ? const Icon(
                                                  Icons.shield_outlined,
                                                  size: 16,
                                                  color: Color(0xFFF59E0B),
                                                )
                                              : null,
                                          onTap: () => _insertMention(agent),
                                        ),
                                      )
                                      .toList(),
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
                    if (widget.estimatedTokens > 0)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 6),
                        child: _ContextDonut(
                          estimatedTokens: widget.estimatedTokens,
                          contextWindow: widget.contextWindow,
                        ),
                      ),
                    Padding(
                      padding: const EdgeInsets.only(bottom: 6),
                      child: _buildThreadControls(context),
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

class _ThreadControlsButton extends StatelessWidget {
  final bool hasOverrides;
  final VoidCallback onPressed;

  const _ThreadControlsButton({
    required this.hasOverrides,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
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
    final Color arcColor;
    if (ratio < 0.5) {
      arcColor = const Color(0xFF10B981);
    } else if (ratio < 0.75) {
      arcColor = const Color(0xFFF59E0B);
    } else {
      arcColor = const Color(0xFFEF4444);
    }

    final tokenLabel = estimatedTokens >= 1000
        ? '${(estimatedTokens / 1000).toStringAsFixed(1)}k'
        : '$estimatedTokens';
    final windowLabel = contextWindow >= 1000
        ? '${(contextWindow / 1000).toStringAsFixed(0)}k'
        : '$contextWindow';

    return Tooltip(
      message: '$tokenLabel / $windowLabel tokens ($percentage%)',
      child: Semantics(
        label:
            'Context usage: $tokenLabel of $windowLabel tokens, $percentage percent',
        child: SizedBox(
          width: 36,
          height: 36,
          child: CustomPaint(
            painter: _DonutPainter(ratio: ratio, arcColor: arcColor),
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
