# B站评论监控 App (Android)

这是一个配套后端服务使用的 Android 客户端，由 Flutter 开发。

## 如何生成 APK (安装包)

如果你已经安装了 Flutter 环境，可以按照以下步骤生成 APK：

### 1. 安装依赖
在 `mobile` 目录下运行：
```bash
flutter pub get
```

### 2. 编译 APK
```bash
flutter build apk --split-per-abi
```
编译完成后，你可以在以下目录找到安装包：
`build/app/outputs/flutter-apk/app-armeabi-v7a-release.apk` (适用于大多数手机)

## 如何使用

1. **配置服务器**：点击右上角设置图标，输入你轻量云服务器的地址 (如 `http://你的IP:8000`)。
2. **填写配置**：在首页填写 B 站 Cookie (SESSDATA) 和钉钉 Webhook 地址，点击“更新配置”。
3. **添加视频**：输入 BV 号并点击“+”号添加到监控列表。
4. **开启监控**：切换“监控状态”开关为运行中。
5. **接收通知**：有新评论时，你会直接在钉钉群收到通知。
