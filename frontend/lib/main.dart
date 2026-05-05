import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:threadbot/screens/chat_screen.dart';
import 'package:flutter_web_plugins/url_strategy.dart';

void main() {
  usePathUrlStrategy();
  runApp(const ThreadBotApp());
}

class ThreadBotApp extends StatelessWidget {
  const ThreadBotApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'ThreadBot',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        textTheme: GoogleFonts.interTextTheme(ThemeData.dark().textTheme),
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF8B5CF6),
          brightness: Brightness.dark,
          surface: const Color(0xFF0D0D12),
          onSurface: const Color(0xFFE4E4E7),
        ),
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xFF0D0D12),
        cardColor: const Color(0xFF16161E),
        dividerColor: const Color(0xFF27272A),
        inputDecorationTheme: InputDecorationTheme(
          fillColor: const Color(0xFF1C1C26),
          filled: true,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(16),
            borderSide: BorderSide.none,
          ),
          contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
          hintStyle: const TextStyle(color: Color(0xFF52525B)),
        ),
      ),
      initialRoute: '/',
      onGenerateRoute: (settings) {
        final uri = Uri.parse(settings.name ?? '/');
        
        if (uri.pathSegments.length == 2 && uri.pathSegments.first == 'thread') {
          return MaterialPageRoute(
            builder: (_) => ChatScreen(initialThreadId: uri.pathSegments[1]),
            settings: settings,
          );
        }
        
        return MaterialPageRoute(
          builder: (_) => const ChatScreen(),
          settings: settings,
        );
      },
    );
  }
}
