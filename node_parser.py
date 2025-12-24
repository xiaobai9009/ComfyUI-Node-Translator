import ast
import os
import logging
import json
from typing import Dict, List, Optional
from src.file_utils import FileUtils

class NodeParser:
    """ComfyUI 节点解析器类
    
    用于解析 Python 文件中的 ComfyUI 节点定义,提取需要翻译的文本信息
    """

    def __init__(self, folder_path: str):
        """初始化节点解析器
        
        Args:
            folder_path: 要解析的文件夹路径
        """
        self.folder_path = folder_path
        self.base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.dirs = FileUtils.init_output_dirs(self.base_path)

    def parse_file(self, file_path: str) -> Dict:
        """解析单个 Python 文件
        
        Args:
            file_path: Python 文件路径
            
        Returns:
            Dict: 解析出的节点信息字典
        """
        logging.info(f"开始解析文件: {file_path}")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # 解析 Python 代码为 AST
        tree = ast.parse(content)
        nodes_info = {}
        
        # 首先获取映射信息
        node_mappings = {}  # 类名到节点名的映射
        display_names = {}  # 节点名到显示名的映射
        
        # 获取 NODE_CLASS_MAPPINGS 和 NODE_DISPLAY_NAME_MAPPINGS
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if 'NODE_CLASS_MAPPINGS' in targets and isinstance(node.value, ast.Dict):
                    # 修改这里的映射获取逻辑
                    for key, value in zip(node.value.keys, node.value.values):
                        if isinstance(key, ast.Str) and isinstance(value, ast.Name):
                            # 反转映射关系：使用类名作为键，映射名作为值
                            class_name = value.id
                            mapped_name = key.s
                            node_mappings[class_name] = mapped_name
                            logging.debug(f"找到节点映射: {class_name} -> {mapped_name}")
                elif 'NODE_DISPLAY_NAME_MAPPINGS' in targets and isinstance(node.value, ast.Dict):
                    for key, value in zip(node.value.keys, node.value.values):
                        if isinstance(key, ast.Str) and isinstance(value, ast.Str):
                            display_names[key.s] = value.s
                            logging.debug(f"找到显示名映射: {key.s} -> {value.s}")
        
        # 解析节点类
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                logging.debug(f"检查类: {node.name}")
                if self._is_comfy_node(node):
                    node_info = self._parse_node_class(node)
                    if node_info:
                        # 获取节点名称的多种可能来源
                        class_name = node.name
                        
                        # 1. 首先尝试从NODE_CLASS_MAPPINGS获取映射名称
                        mapped_name = node_mappings.get(class_name)
                        
                        # 2. 如果没有映射，检查类是否有NODE_NAME属性
                        node_name = getattr(node, 'NODE_NAME', None) if not mapped_name else None
                        
                        # 3. 最后使用类名
                        node_key = mapped_name or node_name or class_name
                        
                        # 获取显示名称的多种可能来源
                        display_name = (
                            display_names.get(node_key) or  # 1. 从NODE_DISPLAY_NAME_MAPPINGS
                            getattr(node, 'NODE_DISPLAY_NAME', None) or  # 2. 类属性
                            node_key  # 3. 默认使用节点键
                        )
                        
                        logging.info(f"解析节点名称: 类名={class_name}, 映射名={mapped_name}, 最终键={node_key}, 显示名={display_name}")
                        
                        # 确保节点信息包含所有必要字段
                        full_node_info = {
                            "_class_name": class_name,  # 保留原始类名
                            "_mapped_name": mapped_name,  # 保留映射名
                            "title": display_name,
                            "inputs": node_info.get("inputs", {}),
                            "widgets": node_info.get("widgets", {}),
                            "outputs": node_info.get("outputs", {}),
                            "tooltips": node_info.get("tooltips", {}),
                            "_source_file": file_path  # 记录源文件路径
                        }
                        
                        nodes_info[node_key] = full_node_info
                        
                        logging.info(f"成功解析完整节点信息: {node_key}")
        
        logging.info(f"文件 {file_path} 解析完成，找到 {len(nodes_info)} 个节点")
        return nodes_info

    def _parse_node_class(self, class_node: ast.ClassDef) -> Optional[Dict]:
        """解析节点类定义
        
        Args:
            class_node: 类定义的 AST 节点
            
        Returns:
            Optional[Dict]: 节点信息字典,如果不是 ComfyUI 节点则返回 None
        """
        if not self._is_comfy_node(class_node):
            return None
            
        node_info = {
            'title': self._get_node_title(class_node),
            'inputs': {},
            'outputs': {},
            'widgets': {},
            'tooltips': {}
        }
        
        # 解析类中的方法和属性
        for item in class_node.body:
            # 检查 INPUT_TYPES 方法
            if isinstance(item, ast.FunctionDef) and item.name == 'INPUT_TYPES':
                # 检查是否是类方法
                if any(isinstance(decorator, ast.Name) and decorator.id == 'classmethod' 
                      for decorator in item.decorator_list):
                    parsed_types = self._parse_input_types_method(item)
                    if parsed_types:
                        # 更新输入
                        if 'inputs' in parsed_types:
                            node_info['inputs'].update(parsed_types['inputs'])
                        # 更新部件
                        if 'widgets' in parsed_types:
                            node_info['widgets'].update(parsed_types['widgets'])
                        # 更新tooltips
                        if 'tooltips' in parsed_types:
                            node_info['tooltips'].update(parsed_types['tooltips'])
            
            # 解析类属性
            elif isinstance(item, ast.Assign):
                targets = [t.id for t in item.targets if isinstance(t, ast.Name)]
                
                # 解析 RETURN_TYPES
                if 'RETURN_TYPES' in targets:
                    return_types = self._parse_return_types(item.value)
                    if return_types:
                        # 为每个返回类型创建默认输出名称
                        for i, return_type in enumerate(return_types):
                            node_info['outputs'][f'output_{i}'] = return_type
                
                # 解析 RETURN_NAMES
                # 注意：这里不使用elif，确保RETURN_NAMES总是被处理
                if 'RETURN_NAMES' in targets:
                    return_names = self._parse_return_names(item.value)
                    if return_names:
                        # 使用自定义名称替换默认输出名称
                        outputs = {}
                        # 确保有足够的输出名称
                        for i, name in enumerate(return_names):
                            # 使用名称作为键和值
                            outputs[name] = name
                        node_info['outputs'] = outputs
                        
                # 解析其他属性
                elif 'CATEGORY' in targets:
                    if isinstance(item.value, ast.Constant):
                        node_info['category'] = item.value.value
                elif 'FUNCTION' in targets:
                    if isinstance(item.value, ast.Constant):
                        node_info['function'] = item.value.value
                elif 'OUTPUT_NODE' in targets:
                    if isinstance(item.value, ast.Constant):
                        node_info['is_output'] = item.value.value
        
        return node_info

    def _is_comfy_node(self, class_node: ast.ClassDef) -> bool:
        """检查类是否是 ComfyUI 节点
        
        Args:
            class_node: 类定义的 AST 节点
            
        Returns:
            bool: 是否是 ComfyUI 节点
        """
        has_input_types = False
        has_return_types = False
        has_category = False
        has_function = False
        
        # 首先检查类方法
        for item in class_node.body:
            # 检查 INPUT_TYPES 方法
            if isinstance(item, ast.FunctionDef) and item.name == 'INPUT_TYPES':
                # 检查是否是类方法或普通方法
                if (any(isinstance(decorator, ast.Name) and decorator.id == 'classmethod' 
                      for decorator in item.decorator_list) or
                    item.name == 'INPUT_TYPES'):
                    has_input_types = True
                
            # 检查类属性
            elif isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        if target.id == 'RETURN_TYPES':
                            has_return_types = True
                        elif target.id == 'CATEGORY':
                            has_category = True
                        elif target.id == 'FUNCTION':
                            has_function = True
        
        # 记录详细信息
        logging.debug(f"节点类 {class_node.name} 检查结果:")
        logging.debug(f"- INPUT_TYPES: {has_input_types}")
        logging.debug(f"- RETURN_TYPES: {has_return_types}")
        logging.debug(f"- CATEGORY: {has_category}")
        logging.debug(f"- FUNCTION: {has_function}")
        
        # 只要满足 INPUT_TYPES 和 RETURN_TYPES 中的一个就认为是节点
        is_node = has_input_types or has_return_types
        
        if is_node:
            logging.info(f"找到 ComfyUI 节点类: {class_node.name}")
        
        return is_node

    def _parse_input_types_method(self, method_node: ast.FunctionDef) -> Dict:
        """解析 INPUT_TYPES 方法，同时提取输入和部件信息
        
        Args:
            method_node: 方法的 AST 节点
            
        Returns:
            Dict: 包含 inputs 和 widgets 的字典
        """
        result = {
            'inputs': {},
            'widgets': {},
            'tooltips': {}
        }
        
        # 查找 return 语句
        for node in ast.walk(method_node):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                # 解析返回的字典
                for key, value in zip(node.value.keys, node.value.values):
                    if isinstance(key, ast.Constant):
                        section_name = key.value  # required, optional, hidden
                        if isinstance(value, ast.Dict):
                            # 解析每个输入/部件定义
                            for item_key, item_value in zip(value.keys, value.values):
                                if isinstance(item_key, ast.Constant):
                                    item_name = item_key.value
                                    # 解析类型元组
                                    if isinstance(item_value, ast.Tuple):
                                        type_info = self._parse_type_tuple(item_value)
                                        
                                        # 提取 tooltip
                                        if 'tooltip' in type_info.get('params', {}):
                                            result['tooltips'][item_name] = type_info['params']['tooltip']
                                        
                                        # 根据类型判断是输入还是部件
                                        if self._is_widget_type(type_info['type']):
                                            # 对于部件，使用名称作为键和值
                                            result['widgets'][item_name] = item_name
                                        else:
                                            # 对于输入，使用名称作为键和值
                                            if section_name in ['required', 'optional', 'hidden']:
                                                result['inputs'][item_name] = item_name
        
        return result

    def _parse_type_tuple(self, tuple_node: ast.Tuple) -> Dict:
        """解析类型元组，提取类型和参数信息
        
        Args:
            tuple_node: 元组的 AST 节点
            
        Returns:
            Dict: 包含类型和参数的字典
        """
        type_info = {
            'type': 'UNKNOWN',
            'params': {}
        }
        
        if len(tuple_node.elts) > 0:
            # 解析类型
            first_element = tuple_node.elts[0]
            if isinstance(first_element, ast.Constant):
                type_info['type'] = first_element.value
            elif isinstance(first_element, ast.Name):
                type_info['type'] = first_element.id
            
            # 解析参数（如果有）
            if len(tuple_node.elts) > 1:
                second_element = tuple_node.elts[1]
                if isinstance(second_element, ast.Dict):
                    for key, value in zip(second_element.keys, second_element.values):
                        if isinstance(key, ast.Constant):
                            param_name = key.value
                            if isinstance(value, ast.Constant):
                                type_info['params'][param_name] = value.value
        
        return type_info

    def _is_widget_type(self, type_name: str) -> bool:
        """判断类型是否是部件类型
        
        Args:
            type_name: 类型名称
            
        Returns:
            bool: 是否是部件类型
        """
        widget_types = {
            'INT', 'FLOAT', 'STRING', 'BOOLEAN', 
            'COMBO', 'DROPDOWN', 'TEXT', 'TEXTAREA',
            'SLIDER', 'CHECKBOX', 'COLOR', 'RADIO',
            'SELECT', 'NUMBER'
        }
        
        # 添加一些常见的输入类型
        input_types = {
            'IMAGE', 'LATENT', 'MODEL', 'VAE', 'CLIP', 
            'CONDITIONING', 'MASK', 'STYLE_MODEL',
            'CONTROL_NET', 'BBOX', 'SEGS'
        }
        
        return (type_name.upper() in widget_types and 
                type_name.upper() not in input_types)

    def _parse_return_types(self, value_node: ast.AST) -> List[str]:
        """解析 RETURN_TYPES 定义
        
        Args:
            value_node: 值的 AST 节点
            
        Returns:
            List[str]: 返回类型列表
        """
        return_types = []
        
        if isinstance(value_node, (ast.Tuple, ast.List)):
            for element in value_node.elts:
                if isinstance(element, ast.Constant):
                    return_types.append(element.value)
                elif isinstance(element, ast.Name):
                    return_types.append(element.id)
                
        return return_types

    def _parse_return_names(self, value_node: ast.AST) -> List[str]:
        """解析 RETURN_NAMES 定义
        
        Args:
            value_node: 值的 AST 节点
            
        Returns:
            List[str]: 返回名称列表
        """
        return_names = []
        
        if isinstance(value_node, (ast.Tuple, ast.List)):
            for element in value_node.elts:
                if isinstance(element, ast.Constant):
                    return_names.append(element.value)
                
        return return_names

    def _get_node_title(self, class_node: ast.ClassDef) -> str:
        """获取节点的显示标题
        
        Args:
            class_node: 类定义的 AST 节点
            
        Returns:
            str: 节点标题
        """
        # 首先查找 NODE_NAME 属性
        for item in class_node.body:
            if isinstance(item, ast.Assign):
                targets = [t.id for t in item.targets if isinstance(t, ast.Name)]
                if 'NODE_NAME' in targets and isinstance(item.value, ast.Str):
                    return item.value.s
                    
        # 如果没有 NODE_NAME 属性,使用类名
        return class_node.name

    def _parse_widgets(self, node_class) -> Dict:
        """解析节点的部件信息
        
        Args:
            node_class: 节点类
            
        Returns:
            Dict: 部件信息字典
        """
        widgets = {}
        
        # 检查类是否有 REQUIRED 属性
        if hasattr(node_class, 'REQUIRED'):
            required = node_class.REQUIRED
            # 遍历所有必需的部件
            for widget_name, widget_type in required.items():
                # 使用原始的部件名称作为值，而不是类型
                widgets[widget_name] = widget_name
                
        # 检查类是否有 OPTIONAL 属性
        if hasattr(node_class, 'OPTIONAL'):
            optional = node_class.OPTIONAL
            # 遍历所有可选的部件
            for widget_name, widget_type in optional.items():
                # 使用原始的部件名称作为值，而不是类型
                widgets[widget_name] = widget_name
                
        return widgets

    def _parse_inputs(self, node_class) -> Dict:
        """解析节点的输入信息
        
        Args:
            node_class: 节点类
            
        Returns:
            Dict: 输入信息字典
        """
        inputs = {}
        
        # 检查类是否有 INPUT_TYPES 属性
        if hasattr(node_class, 'INPUT_TYPES'):
            input_types = node_class.INPUT_TYPES
            # 如果 INPUT_TYPES 是一个字典
            if isinstance(input_types, dict) and 'required' in input_types:
                required = input_types['required']
                # 遍历所有必需的输入
                for input_name, input_type in required.items():
                    # 使用原始的输入名称作为值
                    inputs[input_name] = input_name
                    
        return inputs

    def _parse_outputs(self, node_class) -> Dict:
        """解析节点的输出信息
        
        Args:
            node_class: 节点类
            
        Returns:
            Dict: 输出信息字典
        """
        outputs = {}
        
        # 检查类是否有 RETURN_TYPES 属性
        if hasattr(node_class, 'RETURN_TYPES'):
            return_types = node_class.RETURN_TYPES
            # 遍历所有输出类型
            for i, output_type in enumerate(return_types):
                output_name = f"output_{i}"
                # 使用原始的输出名称作为值
                outputs[output_name] = output_name
                
        return outputs

    def optimize_node_info(self, nodes_info: Dict) -> Dict:
        """优化节点信息，处理特殊的键值情况并规范化格式
        
        Args:
            nodes_info: 原始节点信息字典
            
        Returns:
            Dict: 优化后的节点信息字典
        """
        optimized = {}
        
        # 定义需要替换的类型（包括ComfyUI常见类型）
        type_replacements = {
            'INT': True,
            'FLOAT': True,
            'BOOL': True,
            'STRING': True,
            'NUMBER': True,
            'BOOLEAN': True,
            'IMAGE': True,
            'MASK': True,
            'MODEL': True,
            'LATENT': True,
            'VAE': True,
            'CLIP': True,
            'CONDITIONING': True,
            'CONTROL_NET': True,
            'COMBO': True
        }
        
        # 定义字段顺序
        field_order = ['title', 'inputs', 'widgets', 'outputs', 'tooltips']
        
        for node_name, node_info in nodes_info.items():
            # 创建一个有序字典来保持字段顺序
            optimized_node = {}
            
            # 保留API版本信息（如果存在）
            if '_api_version' in node_info:
                optimized_node['_api_version'] = node_info['_api_version']
            
            # 按照指定顺序添加字段
            for field in field_order:
                if field == 'title':
                    optimized_node['title'] = node_info.get('title', '')
                elif field == 'inputs':
                    optimized_node['inputs'] = {}
                    for input_name, input_value in node_info.get('inputs', {}).items():
                        if input_value in type_replacements:
                            optimized_node['inputs'][input_name] = input_name
                        else:
                            optimized_node['inputs'][input_name] = input_value
                elif field == 'widgets':
                    optimized_node['widgets'] = {}
                    for widget_name, widget_value in node_info.get('widgets', {}).items():
                        if widget_value in type_replacements:
                            optimized_node['widgets'][widget_name] = widget_name
                        else:
                            optimized_node['widgets'][widget_name] = widget_value
                elif field == 'outputs':
                    optimized_node['outputs'] = {}
                    for output_name, output_value in node_info.get('outputs', {}).items():
                        if output_value in type_replacements:
                            optimized_node['outputs'][output_name] = output_name
                        else:
                            optimized_node['outputs'][output_name] = output_value
                elif field == 'tooltips':
                    if 'tooltips' in node_info:
                        optimized_node['tooltips'] = node_info['tooltips']
            
            optimized[node_name] = optimized_node
        
        return optimized

    def parse_folder(self, folder_path: str) -> Dict:
        """解析文件夹中的所有相关文件（递归扫描）"""
        all_nodes = {}
        
        # 获取插件专属的输出目录（仅主目录）
        plugin_output = FileUtils.get_plugin_output_dir(self.base_path, folder_path)
        
        # 结构化数据存储 - 满足用户需求 3, 7
        structure_data = {
            "root_path": folder_path,
            "plugin_name": os.path.basename(folder_path.rstrip(os.path.sep)),
            "directories": {}
        }
        
        debug_info = {
            "total_files": 0,
            "processed_files": 0,
            "found_nodes": 0,
            "file_details": []
        }
        
        # 定义要扫描的文件类型 - 满足用户需求 2
        target_extensions = ['.py', '.js', '.ts', '.json']
        
        # 扫描所有相关文件 - 满足用户需求 1, 5, 6 (在FileUtils中处理)
        try:
            all_files = FileUtils.scan_files(folder_path, target_extensions)
            debug_info["total_files"] = len(all_files)
            logging.info(f"找到 {len(all_files)} 个相关文件")
        except Exception as e:
            logging.error(f"扫描文件夹失败: {str(e)}")
            return {}
        
        # 遍历文件进行处理和归档
        for file_path in all_files:
            try:
                # 计算相对路径作为目录key - 满足用户需求 7
                rel_path = os.path.relpath(os.path.dirname(file_path), folder_path)
                if rel_path == '.': rel_path = ''
                
                # 初始化目录结构条目
                if rel_path not in structure_data["directories"]:
                    structure_data["directories"][rel_path] = {
                        "path": os.path.join(folder_path, rel_path) if rel_path else folder_path,
                        "files": []
                    }
                
                file_ext = os.path.splitext(file_path)[1].lower()
                file_info = {
                    "name": os.path.basename(file_path),
                    "full_path": file_path, # 满足用户需求 4, 7
                    "type": file_ext[1:] if file_ext else "unknown",
                    "nodes": []
                }
                
                # 仅处理 Python 文件提取节点
                if file_ext == '.py':
                    logging.info(f"正在解析文件: {file_path}")
                    
                    # 解析文件
                    nodes = self.parse_file(file_path)
                    
                    if nodes:
                        debug_info["found_nodes"] += len(nodes)
                        all_nodes.update(nodes)
                        file_info["nodes"] = list(nodes.keys())
                        logging.info(f"从文件 {file_path} 中解析出 {len(nodes)} 个节点: {list(nodes.keys())}")
                    else:
                        logging.info(f"文件 {file_path} 中未找到节点")
                
                # 记录文件信息到结构数据
                structure_data["directories"][rel_path]["files"].append(file_info)
                
                # 兼容旧的 debug_info
                debug_info["file_details"].append({
                    "file": file_path,
                    "nodes_found": len(file_info["nodes"]),
                    "node_names": file_info["nodes"]
                })
                
                debug_info["processed_files"] += 1
                
            except Exception as e:
                logging.error(f"处理文件失败 {file_path}: {str(e)}")
                debug_info["file_details"].append({
                    "file": file_path,
                    "error": str(e)
                })
                continue
        
        # 保存结构化信息到临时文件，避免污染结果目录
        try:
            temp_dir = os.path.join(plugin_output['main'], '_temp')
            os.makedirs(temp_dir, exist_ok=True)
            struct_file = os.path.join(temp_dir, 'folder_structure.tmp.json')
            FileUtils.save_json(structure_data, struct_file)
            logging.info(f"目录结构信息已保存: {struct_file}")
        except Exception as e:
            logging.error(f"保存目录结构失败: {e}")

        # 优先尝试V3 API方式（因为V3插件可能会生成传统API兼容层）
        logging.info("尝试使用ComfyUI V3 API方式检测...")
        v3_nodes = self._parse_v3_api(folder_path)
        
        if v3_nodes:
            # 如果V3 API检测到节点，优先使用V3数据
            logging.info(f"使用V3 API检测到 {len(v3_nodes)} 个节点，将使用V3数据")
            all_nodes = v3_nodes  # 完全替换为V3数据
            debug_info["found_nodes"] = len(v3_nodes)
            debug_info["api_version"] = "V3"
        elif len(all_nodes) > 0:
            # 如果V3检测失败但传统API检测到了节点，使用传统数据
            logging.info(f"V3 API未检测到节点，使用传统API检测到的 {len(all_nodes)} 个节点")
            debug_info["api_version"] = "V1/V2"
        else:
            # 两种方式都失败
            debug_info["api_version"] = "Unknown"
            logging.warning("V3 API和传统API都未检测到节点")
        
        
        
        # 优化节点信息
        try:
            optimized_nodes = self.optimize_node_info(all_nodes)
            logging.info(f"成功优化 {len(optimized_nodes)} 个节点的信息")
            return optimized_nodes
        except Exception as e:
            logging.error(f"优化节点信息失败: {str(e)}")
            return all_nodes

    def _parse_v3_api(self, folder_path: str) -> Dict:
        """解析ComfyUI V3 API格式的节点
        
        Args:
            folder_path: 插件文件夹路径
            
        Returns:
            Dict: 解析出的节点信息字典
        """
        logging.info("开始解析ComfyUI V3 API格式...")
        all_nodes = {}
        
        # 1. 查找comfy_entrypoint
        entrypoint_info = self._find_comfy_entrypoint(folder_path)
        if not entrypoint_info:
            logging.info("未找到comfy_entrypoint")
            return {}
        
        logging.info(f"找到comfy_entrypoint: {entrypoint_info}")
        
        # 2. 解析扩展类和节点列表
        extension_file = entrypoint_info.get('file')
        if not extension_file:
            return {}
        
        try:
            with open(extension_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            
            # 查找ComfyExtension类
            node_classes = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # 检查是否继承自ComfyExtension
                    for base in node.bases:
                        if isinstance(base, ast.Name) and base.id == 'ComfyExtension':
                            # 找到get_node_list方法
                            node_list = self._extract_node_list(node)
                            if node_list:
                                node_classes.extend(node_list)
                                logging.info(f"从ComfyExtension中找到节点类: {node_list}")
            
            # 3. 解析每个节点类
            if node_classes:
                # 查找节点类的定义文件
                for node_class_name in node_classes:
                    node_info = self._parse_v3_node_class(folder_path, node_class_name, extension_file)
                    if node_info:
                        all_nodes.update(node_info)
            
        except Exception as e:
            logging.error(f"解析V3 API失败: {str(e)}")
        
        return all_nodes
    
    def _find_comfy_entrypoint(self, folder_path: str) -> Optional[Dict]:
        """查找comfy_entrypoint定义
        
        Args:
            folder_path: 插件文件夹路径
            
        Returns:
            Optional[Dict]: 包含entrypoint信息的字典
        """
        # 首先检查__init__.py
        init_file = os.path.join(folder_path, '__init__.py')
        if os.path.exists(init_file):
            try:
                with open(init_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # 检查是否导入了comfy_entrypoint
                if 'comfy_entrypoint' in content:
                    # 检查是否在当前文件中定义
                    if 'async def comfy_entrypoint' in content or 'def comfy_entrypoint' in content:
                        return {'file': init_file, 'type': 'definition'}

                    # 尝试找到导入的源文件
                    tree = ast.parse(content)
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.ImportFrom, ast.Import)):
                            if isinstance(node, ast.ImportFrom):
                                # from .module import comfy_entrypoint
                                for alias in node.names:
                                    if alias.name == 'comfy_entrypoint':
                                        # 构建源文件路径
                                        if node.module:
                                            module_path = node.module.replace('.', os.sep)
                                            source_file = os.path.join(folder_path, module_path, '__init__.py')
                                            if os.path.exists(source_file):
                                                return {'file': source_file, 'type': 'import'}
                                            # 尝试直接文件
                                            source_file = os.path.join(folder_path, module_path + '.py')
                                            if os.path.exists(source_file):
                                                return {'file': source_file, 'type': 'import'}
            except Exception as e:
                logging.error(f"解析__init__.py失败: {str(e)}")
        
        # 递归搜索所有Python文件
        try:
            py_files = FileUtils.scan_python_files(folder_path)
            for file_path in py_files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # 检查是否定义了comfy_entrypoint函数
                    if 'async def comfy_entrypoint' in content or 'def comfy_entrypoint' in content:
                        return {'file': file_path, 'type': 'definition'}
                except:
                    continue
        except Exception as e:
            logging.error(f"搜索comfy_entrypoint失败: {str(e)}")
        
        return None
    
    def _extract_node_list(self, class_node: ast.ClassDef) -> List[str]:
        """从ComfyExtension类中提取节点列表
        
        Args:
            class_node: ComfyExtension类的AST节点
            
        Returns:
            List[str]: 节点类名列表
        """
        node_list = []
        
        for item in class_node.body:
            if isinstance(item, ast.AsyncFunctionDef) and item.name == 'get_node_list':
                # 查找return语句
                for stmt in ast.walk(item):
                    if isinstance(stmt, ast.Return) and stmt.value:
                        if isinstance(stmt.value, ast.List):
                            # 提取列表中的类名
                            for elt in stmt.value.elts:
                                if isinstance(elt, ast.Name):
                                    node_list.append(elt.id)
        
        return node_list
    
    def _parse_v3_node_class(self, folder_path: str, node_class_name: str, extension_file: str) -> Dict:
        """解析V3 API格式的节点类
        
        Args:
            folder_path: 插件文件夹路径
            node_class_name: 节点类名
            extension_file: 扩展文件路径
            
        Returns:
            Dict: 节点信息字典
        """
        # 首先在extension_file的同目录查找
        extension_dir = os.path.dirname(extension_file)
        
        # 尝试从extension_file中找到导入语句
        try:
            with open(extension_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            
            # 查找节点类的导入
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name == node_class_name:
                            # 找到了导入，构建文件路径
                            if node.module:
                                if node.module.startswith('.'):
                                    # 相对导入
                                    module_path = node.module.lstrip('.').replace('.', os.sep)
                                    node_file = os.path.join(extension_dir, module_path + '.py')
                                else:
                                    # 绝对导入
                                    module_path = node.module.replace('.', os.sep)
                                    node_file = os.path.join(folder_path, module_path + '.py')
                                
                                if os.path.exists(node_file):
                                    return self._parse_v3_node_file(node_file, node_class_name)
        except Exception as e:
            logging.error(f"查找节点类文件失败: {str(e)}")
        
        # 如果没找到，递归搜索所有文件
        try:
            py_files = FileUtils.scan_python_files(folder_path)
            for file_path in py_files:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    if f'class {node_class_name}' in content:
                        return self._parse_v3_node_file(file_path, node_class_name)
                except:
                    continue
        except Exception as e:
            logging.error(f"搜索节点类文件失败: {str(e)}")
        
        return {}
    
    def _parse_v3_node_file(self, file_path: str, node_class_name: str) -> Dict:
        """解析V3节点文件
        
        Args:
            file_path: 节点文件路径
            node_class_name: 节点类名
            
        Returns:
            Dict: 节点信息字典
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            
            # 查找节点类
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == node_class_name:
                    # 查找define_schema方法
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef) and item.name == 'define_schema':
                            return self._parse_define_schema(item, node_class_name, file_path)
        except Exception as e:
            logging.error(f"解析V3节点文件失败 {file_path}: {str(e)}")
        
        return {}
    
    def _parse_define_schema(self, method_node: ast.FunctionDef, node_class_name: str, file_path: str) -> Dict:
        """解析define_schema方法
        
        Args:
            method_node: define_schema方法的AST节点
            node_class_name: 节点类名
            file_path: 源文件路径
            
        Returns:
            Dict: 节点信息字典
        """
        node_info = {
            "title": node_class_name,
            "inputs": {},
            "widgets": {},
            "outputs": {},
            "tooltips": {},
            "_class_name": node_class_name,
            "_mapped_name": None,
            "_source_file": file_path,
            "_api_version": "V3"
        }
        
        # 查找return语句中的io.Schema调用
        for stmt in ast.walk(method_node):
            if isinstance(stmt, ast.Return) and stmt.value:
                if isinstance(stmt.value, ast.Call):
                    # 检查是否是io.Schema调用
                    schema_call = stmt.value
                    
                    # 提取关键字参数
                    for keyword in schema_call.keywords:
                        if keyword.arg == 'node_id' and isinstance(keyword.value, ast.Str):
                            node_info["_mapped_name"] = keyword.value.s
                        elif keyword.arg == 'display_name' and isinstance(keyword.value, ast.Str):
                            node_info["title"] = keyword.value.s
                        elif keyword.arg == 'inputs' and isinstance(keyword.value, ast.List):
                            # 解析输入列表
                            for input_item in keyword.value.elts:
                                input_info = self._parse_v3_input(input_item)
                                if input_info:
                                    if len(input_info) == 3:
                                        name, type_info, tooltip = input_info
                                        node_info["inputs"][name] = type_info
                                        if tooltip:
                                            node_info["tooltips"][name] = tooltip
                                    else:
                                        name, type_info = input_info
                                        node_info["inputs"][name] = type_info
                        elif keyword.arg == 'outputs' and isinstance(keyword.value, ast.List):
                            # 解析输出列表
                            for output_item in keyword.value.elts:
                                output_info = self._parse_v3_output(output_item)
                                if output_info:
                                    name, type_info = output_info
                                    node_info["outputs"][name] = type_info
        
        # 使用node_id或类名作为键
        node_key = node_info.get("_mapped_name") or node_class_name
        
        return {node_key: node_info}
    
    def _parse_v3_input(self, input_node: ast.expr) -> Optional[tuple]:
        """解析V3 API的输入定义
        
        Args:
            input_node: 输入定义的AST节点
            
        Returns:
            Optional[tuple]: (参数名, 参数名, tooltip) 或 None
            注意：返回(参数名, 参数名)是为了与传统API保持一致，
            翻译系统会将第二个值作为待翻译的文本
        """
        try:
            # io.Image.Input("name", ...)
            # io.Int.Input("name", default=0, ...)
            if isinstance(input_node, ast.Call):
                param_name = None
                
                # 1. 获取位置参数名
                if input_node.args and isinstance(input_node.args[0], ast.Str):
                    param_name = input_node.args[0].s
                
                # 2. 获取关键字参数名
                if not param_name:
                    for keyword in input_node.keywords:
                        if keyword.arg == 'name' and isinstance(keyword.value, ast.Str):
                            param_name = keyword.value.s
                            break
                            
                if param_name:
                    tooltip = None
                    # 检查tooltip或description关键字参数
                    for keyword in input_node.keywords:
                        if keyword.arg == 'tooltip' and isinstance(keyword.value, ast.Str):
                            tooltip = keyword.value.s
                        elif keyword.arg == 'description' and isinstance(keyword.value, ast.Str):
                             # 如果没有找到tooltip，使用description作为备选
                             if not tooltip:
                                 tooltip = keyword.value.s
                    
                    # 返回(参数名, 参数名, tooltip)，与传统API格式保持一致
                    # 这样翻译系统会翻译参数名
                    return (param_name, param_name, tooltip)
        except Exception as e:
            logging.debug(f"解析V3输入失败: {str(e)}")
        
        return None
    
    def _parse_v3_output(self, output_node: ast.expr) -> Optional[tuple]:
        """解析V3 API的输出定义
        
        Args:
            output_node: 输出定义的AST节点
            
        Returns:
            Optional[tuple]: (参数名, 参数名) 或 None
            注意：返回(参数名, 参数名)是为了与传统API保持一致，
            翻译系统会将第二个值作为待翻译的文本
        """
        try:
            # io.Image.Output("name")
            # io.Custom(...).Output(display_name="name")
            if isinstance(output_node, ast.Call):
                param_name = None
                
                # 1. 尝试获取位置参数
                if output_node.args and isinstance(output_node.args[0], ast.Str):
                    param_name = output_node.args[0].s
                
                # 2. 尝试获取关键字参数 (display_name 或 name)
                if not param_name:
                    for keyword in output_node.keywords:
                        if keyword.arg in ['display_name', 'name'] and isinstance(keyword.value, ast.Str):
                            param_name = keyword.value.s
                            break
                
                if param_name:
                    # 返回(参数名, 参数名)，与传统API格式保持一致
                    return (param_name, param_name)
        except Exception as e:
            logging.debug(f"解析V3输出失败: {str(e)}")
        
        return None
