import os
import json
from typing import List, Dict
import logging

class FileUtils:
    """文件工具类
    
    处理文件扫描、读写等操作
    """
    
    @staticmethod
    def scan_python_files(folder_path: str) -> List[str]:
        """扫描目录下的所有 Python 文件 (递归)
        
        Args:
            folder_path: 要扫描的文件夹路径
            
        Returns:
            List[str]: Python 文件路径列表
        """
        return FileUtils.scan_files(folder_path, ['.py'])

    @staticmethod
    def scan_files(folder_path: str, extensions: List[str] = None) -> List[str]:
        """递归扫描目录下的指定类型文件
        
        Args:
            folder_path: 要扫描的文件夹路径
            extensions: 文件扩展名列表（如 ['.py', '.js']），如果为 None 则扫描所有文件
            
        Returns:
            List[str]: 文件路径列表
        """
        if not os.path.exists(folder_path):
            raise FileNotFoundError(f"文件夹不存在: {folder_path}")
            
        if not os.path.isdir(folder_path):
            raise NotADirectoryError(f"路径不是文件夹: {folder_path}")
            
        found_files = []
        
        # 规范化扩展名（转小写）
        if extensions:
            extensions = [ext.lower() for ext in extensions]
        
        # 遍历文件夹
        try:
            for root, _, files in os.walk(folder_path):
                for file in files:
                    # 检查扩展名
                    if extensions:
                        _, ext = os.path.splitext(file)
                        if ext.lower() not in extensions:
                            continue
                            
                    # 对于 Python 文件，忽略 __init__.py 和测试文件
                    if file.endswith('.py'):
                        if file == '__init__.py' or file.startswith('test_'):
                            continue

                    full_path = os.path.join(root, file)
                    found_files.append(full_path)
        except PermissionError:
            logging.warning(f"无权限访问目录: {folder_path}")
        except Exception as e:
            logging.error(f"扫描目录出错 {folder_path}: {str(e)}")
                        
        return found_files

    @staticmethod
    def save_json(data: dict, file_path: str):
        """保存 JSON 文件
        
        Args:
            data: 要保存的数据
            file_path: 文件路径
        """
        try:
            # 确保目标目录存在
            os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
            
            # 保存文件
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                
        except Exception as e:
            raise Exception(f"保存 JSON 文件失败: {str(e)}")

    @staticmethod
    def load_json(file_path: str) -> Dict:
        """加载 JSON 文件
        
        Args:
            file_path: JSON 文件路径
            
        Returns:
            Dict: 加载的数据
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
                
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 格式错误: {str(e)}")
        except Exception as e:
            raise IOError(f"读取 JSON 文件失败: {str(e)}")

    @staticmethod
    def merge_json_files(file_paths: List[str], output_file: str) -> None:
        """合并多个 JSON 文件
        
        Args:
            file_paths: JSON 文件路径列表
            output_file: 输出文件路径
        """
        merged_data = {}
        
        for file_path in file_paths:
            try:
                data = FileUtils.load_json(file_path)
                merged_data.update(data)
            except Exception as e:
                logging.warning(f"合并文件 {file_path} 时出错: {str(e)}")
                continue
                
        FileUtils.save_json(merged_data, output_file)

    @staticmethod
    def create_backup(file_path: str) -> str:
        """创建文件备份
        
        Args:
            file_path: 要备份的文件路径
            
        Returns:
            str: 备份文件路径
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
            
        backup_path = file_path + '.bak'
        counter = 1
        
        # 如果备份文件已存在,添加数字后缀
        while os.path.exists(backup_path):
            backup_path = f"{file_path}.bak{counter}"
            counter += 1
            
        try:
            import shutil
            shutil.copy2(file_path, backup_path)
            return backup_path
        except Exception as e:
            raise IOError(f"创建备份失败: {str(e)}")

    @staticmethod
    def is_file_empty(file_path: str) -> bool:
        """检查文件是否为空
        
        Args:
            file_path: 文件路径
            
        Returns:
            bool: 文件是否为空
        """
        return os.path.exists(file_path) and os.path.getsize(file_path) == 0

    @staticmethod
    def get_file_info(file_path: str) -> Dict:
        """获取文件信息
        
        Args:
            file_path: 文件路径
            
        Returns:
            Dict: 文件信息字典
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")
            
        stat = os.stat(file_path)
        return {
            'size': stat.st_size,
            'created': stat.st_ctime,
            'modified': stat.st_mtime,
            'accessed': stat.st_atime
        }

    @staticmethod
    def ensure_dir(dir_path: str) -> None:
        """确保目录存在,不存在则创建
        
        Args:
            dir_path: 目录路径
        """
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

    @staticmethod
    def init_output_dirs(base_path: str) -> dict:
        """初始化输出目录结构，仅创建主输出目录"""
        output_dir = os.path.join(base_path, "output")
        os.makedirs(output_dir, exist_ok=True)
        return {"main": output_dir}

    @staticmethod
    def get_plugin_output_dir(base_path: str, plugin_path: str) -> dict:
        """获取插件对应的输出目录，仅创建插件主目录"""
        plugin_name = os.path.basename(plugin_path.rstrip(os.path.sep))
        plugin_output_dir = os.path.join(base_path, "output", plugin_name)
        os.makedirs(plugin_output_dir, exist_ok=True)
        return {"main": plugin_output_dir}

    @staticmethod
    def save_to_comfyui_translation(plugin_path: str, translation_data: dict, plugin_name: str = None) -> str:
        """保存翻译结果到ComfyUI-DD-Translation目录
        
        Args:
            plugin_path: 插件目录路径（例如：D:/ComfyUI/custom_nodes/sa2va-xj）
            translation_data: 翻译数据
            plugin_name: 插件名称（可选，如果不提供则从路径提取）
            
        Returns:
            str: 保存的文件路径
        """
        try:
            # 获取插件名称
            if not plugin_name:
                plugin_name = os.path.basename(plugin_path.rstrip(os.path.sep))
            
            # 从插件路径推导custom_nodes目录
            # 插件路径格式：.../ComfyUI/custom_nodes/插件名
            plugin_path_normalized = os.path.normpath(plugin_path)
            path_parts = plugin_path_normalized.split(os.sep)
            
            # 查找custom_nodes在路径中的位置
            try:
                custom_nodes_index = path_parts.index('custom_nodes')
                # 重建custom_nodes的完整路径
                custom_nodes_path = os.sep.join(path_parts[:custom_nodes_index + 1])
            except ValueError:
                raise Exception("无法从插件路径中找到custom_nodes目录")
            
            # 构建目标路径：ComfyUI/custom_nodes/ComfyUI-DD-Translation/zh-CN/Nodes
            target_dir = os.path.join(
                custom_nodes_path,
                "ComfyUI-DD-Translation",
                "zh-CN",
                "Nodes"
            )
            
            # 确保目标目录存在
            os.makedirs(target_dir, exist_ok=True)
            
            # 构建目标文件路径
            target_file = os.path.join(target_dir, f"{plugin_name}.json")
            
            # 保存文件（如果存在则覆盖）
            FileUtils.save_json(translation_data, target_file)
            
            return target_file
            
        except Exception as e:
            raise Exception(f"保存到ComfyUI翻译目录失败: {str(e)}")
