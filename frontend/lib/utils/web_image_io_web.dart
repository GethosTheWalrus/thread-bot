import 'dart:async';
import 'dart:html' as html;
import 'dart:typed_data';

class WebImageFile {
  final Uint8List bytes;
  final String filename;
  final String contentType;

  const WebImageFile({
    required this.bytes,
    required this.filename,
    required this.contentType,
  });
}

Future<Uint8List> _readFileBytes(html.File file) async {
  final reader = html.FileReader();
  final completer = Completer<Uint8List>();
  reader.onError.listen((_) {
    if (!completer.isCompleted) {
      completer.completeError(StateError('Failed to read image file'));
    }
  });
  reader.onLoadEnd.listen((_) {
    final result = reader.result;
    if (result is ByteBuffer) {
      completer.complete(Uint8List.view(result));
    } else if (result is Uint8List) {
      completer.complete(result);
    } else {
      completer.completeError(StateError('Unexpected image file data'));
    }
  });
  reader.readAsArrayBuffer(file);
  return completer.future;
}

Future<WebImageFile> _toWebImageFile(html.File file) async {
  final bytes = await _readFileBytes(file);
  final filename = file.name.isNotEmpty ? file.name : 'image.png';
  final contentType = file.type.isNotEmpty ? file.type : 'image/png';
  return WebImageFile(bytes: bytes, filename: filename, contentType: contentType);
}

Future<List<WebImageFile>> pickImageFiles({bool multiple = true}) async {
  final input = html.FileUploadInputElement()
    ..accept = 'image/*'
    ..multiple = multiple;
  final completer = Completer<List<WebImageFile>>();

  void completeEmpty() {
    if (!completer.isCompleted) {
      completer.complete(const []);
    }
  }

  input.onChange.first.then((_) async {
    if (completer.isCompleted) return;
    try {
      final files = input.files ?? const [];
      final images = <WebImageFile>[];
      for (final file in files) {
        if (!file.type.startsWith('image/')) continue;
        images.add(await _toWebImageFile(file));
      }
      if (!completer.isCompleted) completer.complete(images);
    } catch (e, st) {
      if (!completer.isCompleted) completer.completeError(e, st);
    }
  });

  html.window.onFocus.first.then((_) {
    if (input.files == null || input.files!.isEmpty) {
      completeEmpty();
    }
  });

  input.click();
  return completer.future;
}

StreamSubscription<html.Event>? listenForImagePaste(
  Future<void> Function(List<WebImageFile> files) onImages,
) {
  return html.document.onPaste.listen((event) async {
    final active = html.document.activeElement;
    final isTextInput = active is html.InputElement || active is html.TextAreaElement;
    if (!isTextInput) return;

    final clipboard = event.clipboardData;
    if (clipboard == null) return;

    final files = clipboard.files;
    if (files == null || files.isEmpty) return;

    final images = <WebImageFile>[];
    for (final file in files) {
      if (!file.type.startsWith('image/')) continue;
      images.add(await _toWebImageFile(file));
    }

    if (images.isEmpty) return;
    event.preventDefault();
    await onImages(images);
  });
}
