import 'package:flutter/material.dart';

class DashboardWelcome extends StatelessWidget {
  const DashboardWelcome({super.key});

  @override
  Widget build(BuildContext context) {
    return const Padding(
      padding: EdgeInsets.fromLTRB(30, 28, 30, 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [

          Text(
            "Bienvenido",
            style: TextStyle(
              color: Colors.white70,
              fontSize: 18,
            ),
          ),

          SizedBox(height: 8),

          Text(
            "¿Qué quieres analizar hoy?",
            style: TextStyle(
              color: Colors.white,
              fontSize: 34,
              fontWeight: FontWeight.bold,
            ),
          ),

        ],
      ),
    );
  }
}