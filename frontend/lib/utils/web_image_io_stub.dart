import 'dart:async';
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

Future<List<WebImageFile>> pickImageFiles({bool multiple = true}) async => [];

StreamSubscription<dynamic>? listenForImagePaste(
  Future<void> Function(List<WebImageFile> files) onImages,
) {
  return null;
}
