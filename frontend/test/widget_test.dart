import 'package:flutter_test/flutter_test.dart';
import 'package:threadbot/main.dart';

void main() {
  testWidgets('ThreadBot app builds', (WidgetTester tester) async {
    await tester.pumpWidget(const ThreadBotApp());
    await tester.pump();

    expect(find.text('ThreadBot'), findsOneWidget);
  });
}
