class AuthAccount {
  const AuthAccount({
    required this.id,
    required this.email,
    required this.isActive,
    required this.createdAt,
    required this.updatedAt,
    this.displayName,
  });

  final int id;
  final String email;
  final String? displayName;
  final bool isActive;
  final DateTime createdAt;
  final DateTime updatedAt;

  factory AuthAccount.fromMap(Map<String, dynamic> map) {
    final id = map['id'];
    final email = map['email'];
    final isActive = map['isActive'];
    final createdAt = DateTime.tryParse('${map['createdAt']}');
    final updatedAt = DateTime.tryParse('${map['updatedAt']}');
    if (id is! int || id <= 0 || email is! String || email.trim().isEmpty ||
        isActive is! bool || createdAt == null || updatedAt == null) {
      throw const FormatException('Cuenta autenticada no válida.');
    }
    return AuthAccount(
      id: id,
      email: email.trim(),
      displayName: map['displayName'] is String
          ? (map['displayName'] as String).trim().isEmpty
              ? null
              : (map['displayName'] as String).trim()
          : null,
      isActive: isActive,
      createdAt: createdAt.toUtc(),
      updatedAt: updatedAt.toUtc(),
    );
  }
}
