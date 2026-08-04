import 'dart:js_interop';
import 'dart:ui_web' as ui;
import 'package:web/web.dart' as web;

@JS('initPolyBot')
external void _initPolyBot(web.HTMLElement container);

void registerThreadbotViews() {
  void register(String type, String zoom, {bool hideNeedle = false}) {
    ui.platformViewRegistry.registerViewFactory(type, (int viewId) {
      final container = web.HTMLDivElement()
        ..style.width = '100%'
        ..style.height = '100%';
      container.setAttribute('data-zoom', zoom);
      if (hideNeedle) container.setAttribute('data-hide-needle', 'true');
      _initPolyBot(container);
      return container;
    });
  }

  register('poly-bot-view', '4.0');
  register('poly-bot-view-no-needle', '2.5', hideNeedle: true);
}
