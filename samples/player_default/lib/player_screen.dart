import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class PlayerScreen extends StatefulWidget {
  const PlayerScreen({super.key});

  @override
  State<PlayerScreen> createState() => _PlayerScreenState();
}

class _PlayerScreenState extends State<PlayerScreen> {
  @override
  void initState() {
    super.initState();
    // Hide the system bars while a video plays.
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.immersiveSticky);
  }

  @override
  void dispose() {
    SystemChrome.setEnabledSystemUIMode(SystemUiMode.manual, overlays: SystemUiOverlay.values);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        children: const [
          Center(child: AspectRatio(aspectRatio: 16 / 9, child: ColoredBox(color: Colors.white10))),
          Positioned(top: 8, left: 8, child: BackButton(color: Colors.white)),
        ],
      ),
    );
  }
}
