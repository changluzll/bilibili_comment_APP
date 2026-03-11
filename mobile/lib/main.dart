import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'B站评论监控',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.pinkAccent),
        useMaterial3: true,
      ),
      home: const HomePage(),
    );
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key});

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  String baseUrl = '';
  bool isRunning = false;
  List<dynamic> videos = [];
  final TextEditingController _urlController = TextEditingController();
  final TextEditingController _bvController = TextEditingController();
  final TextEditingController _cookieController = TextEditingController();
  final TextEditingController _webhookController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  Future<void> _loadSettings() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      baseUrl = prefs.getString('base_url') ?? '';
      _urlController.text = baseUrl;
    });
    if (baseUrl.isNotEmpty) {
      _fetchStatus();
      _fetchVideos();
    }
  }

  Future<void> _saveSettings() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('base_url', _urlController.text);
    setState(() {
      baseUrl = _urlController.text;
    });
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('设置已保存')),
    );
    _fetchStatus();
    _fetchVideos();
  }

  Future<void> _fetchStatus() async {
    try {
      final response = await http.get(Uri.parse('$baseUrl/status'));
      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        setState(() {
          isRunning = data['is_running'];
        });
      }
    } catch (e) {
      print('获取状态失败: $e');
    }
  }

  Future<void> _fetchVideos() async {
    try {
      final response = await http.get(Uri.parse('$baseUrl/videos'));
      if (response.statusCode == 200) {
        setState(() {
          videos = json.decode(response.body);
        });
      }
    } catch (e) {
      print('获取视频列表失败: $e');
    }
  }

  Future<void> _addVideo() async {
    if (_bvController.text.isEmpty) return;
    try {
      final response = await http.post(
        Uri.parse('$baseUrl/videos'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({'bv_id': _bvController.text}),
      );
      if (response.statusCode == 200) {
        _bvController.clear();
        _fetchVideos();
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('视频已添加')),
        );
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('添加失败: $e')),
      );
    }
  }

  Future<void> _deleteVideo(String oid) async {
    try {
      final response = await http.delete(Uri.parse('$baseUrl/videos/$oid'));
      if (response.statusCode == 200) {
        _fetchVideos();
      }
    } catch (e) {
      print('删除失败: $e');
    }
  }

  Future<void> _toggleJob(bool start) async {
    final endpoint = start ? '/jobs/start' : '/jobs/stop';
    try {
      final response = await http.post(Uri.parse('$baseUrl$endpoint'));
      if (response.statusCode == 200) {
        _fetchStatus();
      }
    } catch (e) {
      print('操作失败: $e');
    }
  }

  Future<void> _updateConfig() async {
    try {
      final response = await http.post(
        Uri.parse('$baseUrl/config'),
        headers: {'Content-Type': 'application/json'},
        body: json.encode({
          'cookie': _cookieController.text.isEmpty ? null : _cookieController.text,
          'dingtalk_webhook': _webhookController.text.isEmpty ? null : _webhookController.text,
        }),
      );
      if (response.statusCode == 200) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('配置已更新')),
        );
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('更新失败: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('B站评论监控'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
        actions: [
          IconButton(
            icon: const Icon(Icons.settings),
            onPressed: () => _showSettingsDialog(),
          ),
        ],
      ),
      body: baseUrl.isEmpty
          ? const Center(child: Text('请先在设置中配置服务器地址'))
          : RefreshIndicator(
              onRefresh: () async {
                await _fetchStatus();
                await _fetchVideos();
              },
              child: ListView(
                padding: const EdgeInsets.all(16),
                children: [
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        children: [
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Text(
                                '监控状态: ${isRunning ? "运行中" : "已停止"}',
                                style: TextStyle(
                                  fontSize: 18,
                                  fontWeight: FontWeight.bold,
                                  color: isRunning ? Colors.green : Colors.red,
                                ),
                              ),
                              Switch(
                                value: isRunning,
                                onChanged: (value) => _toggleJob(value),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  const Text('视频管理', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                  Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _bvController,
                          decoration: const InputDecoration(hintText: '输入 BV 号'),
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.add),
                        onPressed: _addVideo,
                      ),
                    ],
                  ),
                  ListView.builder(
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    itemCount: videos.length,
                    itemBuilder: (context, index) {
                      final video = videos[index];
                      return ListTile(
                        title: Text(video['title']),
                        subtitle: Text(video['bv_id']),
                        trailing: IconButton(
                          icon: const Icon(Icons.delete, color: Colors.grey),
                          onPressed: () => _deleteVideo(video['oid']),
                        ),
                      );
                    },
                  ),
                  const SizedBox(height: 16),
                  const Text('快速配置', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
                  TextField(
                    controller: _cookieController,
                    decoration: const InputDecoration(labelText: 'B站 Cookie (SESSDATA)'),
                  ),
                  TextField(
                    controller: _webhookController,
                    decoration: const InputDecoration(labelText: '钉钉 Webhook'),
                  ),
                  const SizedBox(height: 8),
                  ElevatedButton(
                    onPressed: _updateConfig,
                    child: const Text('更新配置'),
                  ),
                ],
              ),
            ),
    );
  }

  void _showSettingsDialog() {
    showDialog(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('服务器设置'),
        content: TextField(
          controller: _urlController,
          decoration: const InputDecoration(hintText: 'http://ip:8000'),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('取消'),
          ),
          TextButton(
            onPressed: () {
              _saveSettings();
              Navigator.pop(context);
            },
            child: const Text('保存'),
          ),
        ],
      ),
    );
  }
}
