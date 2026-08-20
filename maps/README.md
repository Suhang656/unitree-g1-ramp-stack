# 参考点云

GitHub 中的 NX 参考点云按二进制字节分成四段，以便通过受限连接稳定发布。它们不是四张独立地图。

在仓库根目录执行：

```bash
bash maps/assemble_reference_map.sh
```

脚本会生成：

```text
maps/g1_embodied_lab_panorama_v2_nx_reference.pcd
```

并核验 SHA256：

```text
ca085ee9796feb252521228b1e3fb375985cee87c1a2a2fc46116cecfa8c05c3
```

该文件是 NX 侧保存的参考点云，不等同于 Unitree 官方 SLAM 控制单元内部地图。请继续遵循 `docs/MAP_MIGRATION.md`。
