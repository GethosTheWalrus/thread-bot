import 'package:flutter/material.dart';

const agentViolet = Color(0xFF8B5CF6);
const agentSurface = Color(0xFF16161E);
const agentSurfaceRaised = Color(0xFF1C1C26);
const agentBorder = Color(0xFF2A2A36);

Color agentStatusColor(String status) {
  switch (status.toLowerCase()) {
    case 'active':
    case 'succeeded':
      return const Color(0xFF55D68A);
    case 'running':
    case 'evaluating':
      return const Color(0xFF8FB8FF);
    case 'draft':
    case 'waiting_approval':
      return const Color(0xFFF2C66D);
    case 'paused':
    case 'queued':
      return const Color(0xFF70A8E8);
    case 'failed':
    case 'error':
    case 'cancelled':
      return const Color(0xFFF07F8A);
    default:
      return Colors.white54;
  }
}

class AgentStatusPill extends StatelessWidget {
  final String status;
  const AgentStatusPill(this.status, {super.key});
  @override
  Widget build(BuildContext context) {
    final color = agentStatusColor(status);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .12),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: .28)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 6,
            height: 6,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
          Text(
            status.replaceAll('_', ' '),
            style: TextStyle(
              color: color,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

class AgentIdentity extends StatelessWidget {
  final String name;
  final String? handle;
  final double radius;
  const AgentIdentity({
    super.key,
    required this.name,
    this.handle,
    this.radius = 22,
  });
  @override
  Widget build(BuildContext context) => Row(
    children: [
      CircleAvatar(
        radius: radius,
        backgroundColor: agentViolet.withValues(alpha: .16),
        child: Text(
          name.isEmpty ? '?' : name.substring(0, 1).toUpperCase(),
          style: TextStyle(
            color: const Color(0xFFC4B5FD),
            fontSize: radius * .72,
            fontWeight: FontWeight.w700,
          ),
        ),
      ),
      const SizedBox(width: 12),
      Expanded(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
            ),
            if (handle?.isNotEmpty == true)
              Text(
                '@$handle',
                style: const TextStyle(color: Color(0xFFA78BFA), fontSize: 12),
              ),
          ],
        ),
      ),
    ],
  );
}

class AgentBreadcrumb extends StatelessWidget {
  final String current;
  final VoidCallback? onBack;
  const AgentBreadcrumb({super.key, required this.current, this.onBack});
  @override
  Widget build(BuildContext context) => Row(
    children: [
      IconButton(
        tooltip: 'Back to Agents',
        onPressed: onBack ?? () => Navigator.maybePop(context),
        icon: const Icon(Icons.arrow_back_rounded, size: 20),
      ),
      const Text(
        'Agents',
        style: TextStyle(color: Colors.white54, fontSize: 13),
      ),
      const Padding(
        padding: EdgeInsets.symmetric(horizontal: 8),
        child: Icon(
          Icons.chevron_right_rounded,
          size: 16,
          color: Colors.white30,
        ),
      ),
      Flexible(
        child: Text(
          current,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
        ),
      ),
    ],
  );
}

class AgentPageHeader extends StatelessWidget {
  final String eyebrow, title, description;
  final Widget? action;
  const AgentPageHeader({
    super.key,
    required this.eyebrow,
    required this.title,
    required this.description,
    this.action,
  });
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final copy = Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            eyebrow.toUpperCase(),
            style: const TextStyle(
              color: Color(0xFFA78BFA),
              fontSize: 11,
              fontWeight: FontWeight.w700,
              letterSpacing: 1.2,
            ),
          ),
          const SizedBox(height: 7),
          Text(
            title,
            style: const TextStyle(
              fontSize: 28,
              fontWeight: FontWeight.w800,
              letterSpacing: -.4,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            description,
            style: const TextStyle(color: Colors.white60, height: 1.4),
          ),
        ],
      );
      return Padding(
        padding: const EdgeInsets.only(bottom: 24),
        child: constraints.maxWidth < 620
            ? Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  copy,
                  if (action != null) ...[const SizedBox(height: 16), action!],
                ],
              )
            : Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Expanded(child: copy),
                  if (action != null) ...[const SizedBox(width: 16), action!],
                ],
              ),
      );
    },
  );
}

class AgentSection extends StatelessWidget {
  final String title, description;
  final Widget child;
  final Widget? trailing;
  const AgentSection({
    super.key,
    required this.title,
    this.description = '',
    required this.child,
    this.trailing,
  });
  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(bottom: 16),
    padding: const EdgeInsets.all(18),
    decoration: BoxDecoration(
      color: agentSurface,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: agentBorder),
    ),
    child: LayoutBuilder(
      builder: (context, constraints) {
        final heading = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
            ),
            if (description.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                description,
                style: const TextStyle(
                  color: Colors.white54,
                  fontSize: 12,
                  height: 1.35,
                ),
              ),
            ],
          ],
        );
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (trailing == null)
              heading
            else if (constraints.maxWidth < 520) ...[
              heading,
              const SizedBox(height: 12),
              trailing!,
            ] else
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: heading),
                  const SizedBox(width: 16),
                  trailing!,
                ],
              ),
            const SizedBox(height: 14),
            child,
          ],
        );
      },
    ),
  );
}

class AgentMetric extends StatelessWidget {
  final String label, value;
  final IconData icon;
  const AgentMetric({
    super.key,
    required this.label,
    required this.value,
    required this.icon,
  });
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(
      color: agentSurfaceRaised,
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: agentBorder),
    ),
    child: Row(
      children: [
        Icon(icon, size: 18, color: const Color(0xFFA78BFA)),
        const SizedBox(width: 10),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                value,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w700,
                ),
              ),
              Text(
                label,
                style: const TextStyle(color: Colors.white54, fontSize: 11),
              ),
            ],
          ),
        ),
      ],
    ),
  );
}

class AgentStateView extends StatelessWidget {
  final IconData icon;
  final String title, message;
  final VoidCallback? onAction;
  final String actionLabel;
  const AgentStateView({
    super.key,
    this.icon = Icons.inbox_outlined,
    required this.title,
    required this.message,
    this.onAction,
    this.actionLabel = 'Try again',
  });
  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 42, color: Colors.white30),
          const SizedBox(height: 14),
          Text(
            title,
            style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 6),
          Text(
            message,
            textAlign: TextAlign.center,
            style: const TextStyle(color: Colors.white54),
          ),
          if (onAction != null) ...[
            const SizedBox(height: 16),
            FilledButton.tonal(onPressed: onAction, child: Text(actionLabel)),
          ],
        ],
      ),
    ),
  );
}
