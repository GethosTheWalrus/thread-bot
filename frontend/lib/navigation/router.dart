import 'package:flutter/material.dart';
import 'package:threadbot/screens/chat_screen.dart';
import 'package:threadbot/navigation/app_shell.dart' show AuthScreen;
import 'package:threadbot/screens/autonomy_screens.dart';
import 'package:threadbot/screens/agent_list_screen.dart';
import 'package:threadbot/screens/agent_detail_screen.dart';
import 'package:threadbot/screens/mcp_screen.dart';
import 'package:threadbot/screens/settings_screen.dart';
import 'package:threadbot/screens/skills_screen.dart';
import 'package:threadbot/screens/osrs_loadouts_screen.dart';
import 'package:threadbot/services/autonomy_api.dart';

Route<dynamic> appRoute(RouteSettings settings, AutonomyApiService api) {
  final path = Uri.parse(settings.name ?? '/').path;
  final parts = path.split('/').where((x) => x.isNotEmpty).toList();
  if (path == '/auth')
    return MaterialPageRoute(
      builder: (_) => AuthScreen(api: api),
      settings: settings,
    );
  if (path == '/agents-list')
    return MaterialPageRoute(
      builder: (_) => AgentListScreen(api: api),
      settings: settings,
    );
  if (path == '/agents') return _redirect('/', settings);
  if (path == '/agents/new')
    return MaterialPageRoute(
      builder: (_) => NewAgentScreen(api: api),
      settings: settings,
    );
  if (path == '/audit' || path == '/approvals' || path == '/operations')
    return _redirect('/', settings);
  if (path == '/skills')
    return MaterialPageRoute(
      builder: (_) => const SkillsScreen(),
      settings: settings,
    );
  if (path == '/mcp')
    return MaterialPageRoute(
      builder: (_) => const MCPScreen(),
      settings: settings,
    );
  if (path == '/settings')
    return MaterialPageRoute(
      builder: (_) => SettingsScreen(onUnauthorized: api.onUnauthorized),
      settings: settings,
    );
  if (path == '/osrs-loadouts')
    return MaterialPageRoute(
      builder: (_) => const OsrsLoadoutsScreen(),
      settings: settings,
    );
  if (parts.length == 2 && parts[0] == 'thread')
    return MaterialPageRoute(
      builder: (_) => ChatScreen(
        initialThreadId: parts[1],
        onUnauthorized: api.onUnauthorized,
      ),
      settings: settings,
    );
  if (parts.length == 2 && parts[0] == 'agent-details')
    return MaterialPageRoute(
      builder: (_) => AgentDetailScreen(id: parts[1], api: api),
      settings: settings,
    );
  if (parts.length == 2 && parts[0] == 'agents')
    return MaterialPageRoute(
      builder: (_) => AgentEditorScreen(id: parts[1], api: api),
      settings: settings,
    );
  if (parts.length == 2 && parts[0] == 'agent-runs')
    return MaterialPageRoute(
      builder: (_) => RunScreen(id: parts[1], api: api),
      settings: settings,
    );
  if (path == '/' || path.isEmpty)
    return MaterialPageRoute(
      builder: (_) => ChatScreen(onUnauthorized: api.onUnauthorized),
      settings: settings,
    );
  return MaterialPageRoute(
    builder: (_) => Scaffold(
      appBar: AppBar(title: const Text('Not found')),
      body: Center(child: Text('No route for $path')),
    ),
    settings: settings,
  );
}

Route<dynamic> _redirect(String destination, RouteSettings settings) =>
    MaterialPageRoute(
      settings: settings,
      builder: (_) => _LegacyRedirect(destination: destination),
    );

class _LegacyRedirect extends StatefulWidget {
  final String destination;
  const _LegacyRedirect({required this.destination});
  @override
  State<_LegacyRedirect> createState() => _LegacyRedirectState();
}

class _LegacyRedirectState extends State<_LegacyRedirect> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted)
        Navigator.of(context).pushReplacementNamed(widget.destination);
    });
  }

  @override
  Widget build(BuildContext context) => const SizedBox.shrink();
}
