import 'dart:ui_web' as ui;
import 'package:web/web.dart' as web;
import 'dart:js_interop';

@JS('initPolyBot')
external void _initPolyBot(web.HTMLElement container);

void registerThreadbotViews() {
  // Register Three.js PolyBot view globally (Full Mascot for Welcome Screen)
  ui.platformViewRegistry.registerViewFactory(
    'poly-bot-view',
    (int viewId) {
      final container = web.HTMLDivElement()
        ..style.width = '100%'
        ..style.height = '100%';
      container.setAttribute('data-zoom', '4.0');
      
      Future.delayed(const Duration(milliseconds: 100), () {
        _initPolyBot(container);
      });

      return container;
    },
  );

  // Register version without needle/thread for chat replies (Zoomed-in Headshot)
  ui.platformViewRegistry.registerViewFactory(
    'poly-bot-view-no-needle',
    (int viewId) {
      final container = web.HTMLDivElement()
        ..style.width = '100%'
        ..style.height = '100%';
      container.setAttribute('data-hide-needle', 'true');
      container.setAttribute('data-zoom', '2.5'); // Closer "hero" zoom for face
      
      Future.delayed(const Duration(milliseconds: 100), () {
        _initPolyBot(container);
      });

      return container;
    },
  );
}
