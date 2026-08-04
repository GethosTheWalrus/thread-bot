import 'dart:ui_web' as ui;
import 'package:flutter/widgets.dart';
import 'package:web/web.dart' as web;

int _nextId = 0;
final Map<String, String> _videoTypes = <String, String>{};
final Map<String, String> _slotUrls = <String, String>{};
const _maxVideoFactories = 32;
String registerInlineVideo(String url) {
  final existing = _videoTypes[url];
  if (existing != null) return existing;
  final slot = _nextId++ % _maxVideoFactories;
  final type = 'threadbot-video-$slot';
  final oldUrl = _slotUrls[type];
  if (oldUrl != null) {
    _videoTypes.remove(oldUrl);
  }
  _videoTypes[url] = type;
  _slotUrls[type] = url;
  if (oldUrl == null)
    ui.platformViewRegistry.registerViewFactory(type, (int viewId) {
      final source = _slotUrls[type] ?? url;
      final video = web.HTMLVideoElement()
        ..src = source
        ..controls = true
        ..loop = true
        ..preload = 'metadata';
      video.style.width = '100%';
      video.style.height = '100%';
      video.style.borderRadius = '12px';
      video.style.backgroundColor = '#000000';
      return video;
    });
  return type;
}

Widget inlineVideoView(String viewType) => HtmlElementView(viewType: viewType);
