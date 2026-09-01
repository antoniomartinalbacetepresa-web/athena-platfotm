import 'package:flutter/material.dart';

import '../theme/athena_colors.dart';

class AthenaText {
  AthenaText._();

  static const h1 = TextStyle(
    color: AthenaColors.text,
    fontSize: 34,
    fontWeight: FontWeight.bold,
  );

  static const h2 = TextStyle(
    color: AthenaColors.text,
    fontSize: 28,
    fontWeight: FontWeight.bold,
  );

  static const h3 = TextStyle(
    color: AthenaColors.text,
    fontSize: 22,
    fontWeight: FontWeight.bold,
  );

  static const title = TextStyle(
    color: AthenaColors.text,
    fontSize: 18,
    fontWeight: FontWeight.w600,
  );

  static const body = TextStyle(
    color: AthenaColors.text,
    fontSize: 16,
  );

  static const caption = TextStyle(
    color: AthenaColors.textSecondary,
    fontSize: 13,
  );

  static const small = TextStyle(
    color: AthenaColors.textSecondary,
    fontSize: 11,
  );

  static const score = TextStyle(
    color: Color(0xFF45D483),
    fontSize: 42,
    fontWeight: FontWeight.bold,
  );
}