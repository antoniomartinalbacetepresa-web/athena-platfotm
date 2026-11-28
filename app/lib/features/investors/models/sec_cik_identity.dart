/// SEC Central Index Key identity: leading zeros are formatting, not identity.
/// Reject zero and malformed identifiers rather than counting aliases as managers.
String normalizeSecCik(String value) {
  final raw = value.trim();
  if (!RegExp(r'^\d{1,10}$').hasMatch(raw)) {
    throw const FormatException('CIK SEC inválido.');
  }
  final canonical = raw.replaceFirst(RegExp(r'^0+'), '');
  if (canonical.isEmpty) {
    throw const FormatException('CIK SEC debe ser positivo.');
  }
  return canonical;
}
