# Copyright (c) 2015 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.

"""
Hook that loads defines all the available actions, broken down by publish type. 
"""

import glob
import os
import re
import pymel.core as pm
import maya.cmds as cmds
import maya.mel as mel
import sgtk
import json

HookBaseClass = sgtk.get_hook_baseclass()
class MayaActions(HookBaseClass):
    
    ##############################################################################################################
    # public interface - to be overridden by deriving classes 
    
    def generate_actions(self, sg_publish_data, actions, ui_area):
        """
        Returns a list of action instances for a particular publish.
        This method is called each time a user clicks a publish somewhere in the UI.
        The data returned from this hook will be used to populate the actions menu for a publish.
    
        The mapping between Publish types and actions are kept in a different place
        (in the configuration) so at the point when this hook is called, the loader app
        has already established *which* actions are appropriate for this object.
        
        The hook should return at least one action for each item passed in via the 
        actions parameter.
        
        This method needs to return detailed data for those actions, in the form of a list
        of dictionaries, each with name, params, caption and description keys.
        
        Because you are operating on a particular publish, you may tailor the output 
        (caption, tooltip etc) to contain custom information suitable for this publish.
        
        The ui_area parameter is a string and indicates where the publish is to be shown. 
        - If it will be shown in the main browsing area, "main" is passed. 
        - If it will be shown in the details area, "details" is passed.
        - If it will be shown in the history area, "history" is passed. 
        
        Please note that it is perfectly possible to create more than one action "instance" for 
        an action! You can for example do scene introspection - if the action passed in 
        is "character_attachment" you may for example scan the scene, figure out all the nodes
        where this object can be attached and return a list of action instances:
        "attach to left hand", "attach to right hand" etc. In this case, when more than 
        one object is returned for an action, use the params key to pass additional 
        data into the run_action hook.
        
        :param sg_publish_data: Shotgun data dictionary with all the standard publish fields.
        :param actions: List of action strings which have been defined in the app configuration.
        :param ui_area: String denoting the UI Area (see above).
        :returns List of dictionaries, each with keys name, params, caption and description
        """
        app = self.parent
        app.log_debug("Generate actions called for UI element %s. "
                      "Actions: %s. Publish Data: %s" % (ui_area, actions, sg_publish_data))
        
        action_instances = []
        
        if "reference" in actions:
            action_instances.append( {"name": "reference", 
                                      "params": None,
                                      "caption": "Create Reference", 
                                      "description": "This will add the item to the scene as a standard reference."} )

        if "import" in actions:
            action_instances.append( {"name": "import", 
                                      "params": None,
                                      "caption": "Import into Scene", 
                                      "description": "This will import the item into the current scene."} )
        if "link" in actions:
            action_instances.append( {"name": "link",
                                      "params": None,
                                      "caption": "Link File Path",
                                      "description": "This will link the file with related objects."} )

        if "texture_node" in actions:
            action_instances.append( {"name": "texture_node",
                                      "params": None, 
                                      "caption": "Create Texture Node", 
                                      "description": "Creates a file texture node for the selected item.."} )
            
        if "udim_texture_node" in actions:
            # Special case handling for Mari UDIM textures as these currently only load into 
            # Maya 2015 in a nice way!
            if self._get_maya_version() >= 2015:
                action_instances.append( {"name": "udim_texture_node",
                                          "params": None, 
                                          "caption": "Create Texture Node", 
                                          "description": "Creates a file texture node for the selected item.."} )

        if "image_plane" in actions:
            action_instances.append({
                "name": "image_plane",
                "params": None,
                "caption": "Create Image Plane",
                "description": "Creates an image plane for the selected item.."
            })

        return action_instances

    def execute_multiple_actions(self, actions):
        """
        Executes the specified action on a list of items.

        The default implementation dispatches each item from ``actions`` to
        the ``execute_action`` method.

        The ``actions`` is a list of dictionaries holding all the actions to execute.
        Each entry will have the following values:

            name: Name of the action to execute
            sg_publish_data: Publish information coming from Shotgun
            params: Parameters passed down from the generate_actions hook.

        .. note::
            This is the default entry point for the hook. It reuses the ``execute_action``
            method for backward compatibility with hooks written for the previous
            version of the loader.

        .. note::
            The hook will stop applying the actions on the selection if an error
            is raised midway through.

        :param list actions: Action dictionaries.
        """
        for single_action in actions:
            name = single_action["name"]
            print "action_name:",name
            sg_publish_data = single_action["sg_publish_data"]
            params = single_action["params"]
            self.execute_action(name, params, sg_publish_data)

    def execute_action(self, name, params, sg_publish_data):
        """
        Execute a given action. The data sent to this be method will
        represent one of the actions enumerated by the generate_actions method.
        
        :param name: Action name string representing one of the items returned by generate_actions.
        :param params: Params data, as specified by generate_actions.
        :param sg_publish_data: Shotgun data dictionary with all the standard publish fields.
        :returns: No return value expected.
        """
        app = self.parent
        app.log_debug("Execute action called for action %s. "
                      "Parameters: %s. Publish Data: %s" % (name, params, sg_publish_data))
        
        # resolve path
        # toolkit uses utf-8 encoded strings internally and Maya API expects unicode
        # so convert the path to ensure filenames containing complex characters are supported
        path = self.get_publish_path(sg_publish_data).decode("utf-8")
        
        if name == "reference":
            self._create_reference(path, sg_publish_data)

        if name == "import":
            self._do_import(path, sg_publish_data)
        
        if name == "texture_node":
            self._create_texture_node(path, sg_publish_data)
            
        if name == "udim_texture_node":
            self._create_udim_texture_node(path, sg_publish_data)

        if name == "image_plane":
            self._create_image_plane(path, sg_publish_data)
        if name == "link":
            self._do_link(path,sg_publish_data)
        # update scene time
        update_scene_time()
        # update render setting
        from func import _shotgun_server,replace_special_character as rsc

        sg = _shotgun_server._shotgun()
        task = sg_publish_data.get('task')
        task_find = sg.find_one('Task', [['id', 'is', task.get('id')]], ['step'])
        import_preset_step = [150,155,7,144]
        publish_file_step = task_find.get('step').get('id')
        if publish_file_step in import_preset_step:
            current_dir,filename = os.path.split(path)
            current_dir = rsc.replaceSpecialCharacter(current_dir)
            load_path = current_dir
            if 'lightRig' not in current_dir:
                load_path = load_path + "/lightRig"
            _files = os.listdir(load_path)
            for _f in _files:
                if _f.endswith('.json'):
                    print _f
                    preset_name = _f.split(".")[0]
                    self._load_render_setting(preset_name,load_path)
                    break
        # udpate resolution
        update_resolution()
    ##############################################################################################################
    # helper methods which can be subclassed in custom hooks to fine tune the behaviour of things
    
    def _create_reference(self, path, sg_publish_data):
        """
        Create a reference with the same settings Maya would use
        if you used the create settings dialog.
        
        :param path: Path to file.
        :param sg_publish_data: Shotgun data dictionary with all the standard publish fields.
        """
        # return
        app = self.parent
        app.logger.debug("reference_path:%s"%path)
        if not os.path.exists(path):
            raise Exception("File not found on disk - '%s'" % path)
        
        # make a name space out of entity name + publish name
        # e.g. bunny_upperbody
        # namespace = "%s %s" % (sg_publish_data.get("entity").get("name"), sg_publish_data.get("name"))

        # layout , animation, preshot load mode changed to import
        import_step = [35]
        published_file_type = sg_publish_data.get('published_file_type').get('name')
        if published_file_type != "MAYA Camera":
            from func import _shotgun_server
            sg = _shotgun_server._shotgun()
            task = sg_publish_data.get('task')
            task_find = sg.find_one('Task',[['id','is',task.get('id')]],['step'])
            if task_find.get('step').get('id') in import_step:
                self._do_import(path,sg_publish_data)
                return
        # no_namespace_step = [136,15]
        # engine = sgtk.platform.current_engine()
        # context = engine.context
        # current_step = context.step
        # if current_step.get('id') in no_namespace_step:
        #     namespace = ":"
        # else:
        name = sg_publish_data.get('name')
        namespace = (name.split(".")[0])
        namespace = namespace.replace(" ", "_")

        # print sg_publish_data

        pm.system.createReference(path,
                                  loadReferenceDepth= "all",
                                  mergeNamespacesOnClash=False,
                                  namespace=namespace)

        cmds.referenceQuery(path, referenceNode=True)

        # give material if file type is maya shader 
        shader_type = "Maya Shader Network"

        if published_file_type == shader_type:
            _hookup_shaders("SHADER_HOOKUP_","mesh")
        xgshader_type = "MAYA XGShader"
        if published_file_type == xgshader_type:
            filename = os.path.basename(path)
            if not re.search("_GRM",filename):
                cmds.file(path,rr = True)
                raise Exception("XGen shader file name error!")
            collection = filename.split("_GRM")[0]
            if not cmds.objExists(collection):
                cmds.file(path, rr=True)
                raise Exception("%s dose not exists!"%collection)
            _hookup_shaders("XGSHADER_HOOKUP_","xgmDescription",str(collection))
            return

    def _do_import(self, path, sg_publish_data):
        """
        Create a reference with the same settings Maya would use
        if you used the create settings dialog.
        
        :param path: Path to file.
        :param sg_publish_data: Shotgun data dictionary with all the standard publish fields.
        """
        if not os.path.exists(path):
            raise Exception("File not found on disk - '%s'" % path)
                
        # make a name space out of entity name + publish name
        # e.g. bunny_upperbody                
        # namespace = "%s %s" % (sg_publish_data.get("entity").get("name"), sg_publish_data.get("name"))
        published_file_type = sg_publish_data.get('published_file_type').get('name')
        xgen_type = "Maya XGen"
        if published_file_type == xgen_type:
            _hookup_xgen(path)
            return

        namespace = (sg_publish_data.get('name').split(".")[0])
        namespace = namespace.replace(" ", "_")
        if published_file_type == "MAYA XGGeometry":
            namespace = ":"
        # perform a more or less standard maya import, putting all nodes brought in into a specific namespace
        cmds.file(path, i=True, renameAll=True, namespace=namespace, loadReferenceDepth="all", preserveReferences=True)
        try:
            mel.eval('source "removeAllNameSpace.mel";')
            mel.eval('removeAllNameSpace();')
        except:
            pass
    def _do_link(self,path,sg_publish_data):
        print "do link..."
        published_file_type = sg_publish_data.get('published_file_type').get('name')

        if published_file_type == "Maya SIMCRV":
            _hookup_simcrv(path)

    def _create_texture_node(self, path, sg_publish_data):
        """
        Create a file texture node for a texture
        
        :param path:             Path to file.
        :param sg_publish_data:  Shotgun data dictionary with all the standard publish fields.
        :returns:                The newly created file node
        """
        # sg_publish_data:{'code': 'table_textures_v003',
        #                  'image': 'http://sg.anime.com/thumbnail/api_image/23805?AccessKeyId=uTbPnnWUNhn2nSG7Agrp&Expires=1566523439&Signature=riY0q0SNnengbKqAZgGGG2ueX0IgFwbtah2vhp6qMnQ%3D',
        #                  'entity': {'type': 'Asset', 'id': 1774, 'name': 'table'}, 'task.Task.sg_status_list': 'wtg',
        #                  'id': 4408, 'task.Task.content': 'texture',
        #                  'created_by': {'type': 'HumanUser', 'id': 146, 'name': 'huang.sheng'}, 'version': None,
        #                  'sg_status_list': 'wtg', 'type': 'PublishedFile', 'version.Version.sg_status_list': None,
        #                  'description': None, 'task_uniqueness': False, 'path': {
        #         'local_path_windows': '\\\\3par\\ibrix01\\shotgun\\shotgun_work\\tdprojects\\assets\\Environment\\table\\TXT\\publish\\substancepainter\\textures\\table_textures_v003',
        #         'name': 'table_textures_v003',
        #         'local_path_linux': '/shotgun/shotgun_work/tdprojects/assets/Environment/table/TXT/publish/substancepainter/textures/table_textures_v003',
        #         'url': 'file://\\\\3par\\ibrix01\\shotgun\\shotgun_work\\tdprojects\\assets\\Environment\\table\\TXT\\publish\\substancepainter\\textures\\table_textures_v003',
        #         'local_storage': {'type': 'LocalStorage', 'id': 2, 'name': 'CFA  LocalStorage'},
        #         'local_path': '\\\\3par\\ibrix01\\shotgun\\shotgun_work\\tdprojects\\assets\\Environment\\table\\TXT\\publish\\substancepainter\\textures\\table_textures_v003',
        #         'content_type': None, 'local_path_mac': None, 'type': 'Attachment', 'id': 20382, 'link_type': 'local'},
        #                  'task.Task.due_date': None, 'version_number': 3,
        #                  'task': {'type': 'Task', 'id': 16331, 'name': 'texture'}, 'name': 'Asset_textures',
        #                  'created_at': datetime.datetime(2019, 8, 21, 15, 34, 13,
        #                                                  tzinfo= < tank_vendor.shotgun_api3.lib.sgtimezone.LocalTimezone
        #                  object at 0x000002E40072CF98 >), 'created_by.HumanUser.image': None, 'published_file_type': {
        #                                                                                                                  'type': 'PublishedFileType',
        #                                                                                                                  'id': 16,
        #                                                                                                                  'name': 'Texture Folder'}, 'project': {
        #     'type': 'Project', 'id': 99, 'name': 'TDProjects'}}
        file_type =  sg_publish_data.get("published_file_type").get("name")
        if file_type == 'Texture Folder':
            return self._create_texture_nodes_byfolder(path,sg_publish_data)
        return self._create_texture_node_func(path,sg_publish_data)
    def _create_texture_node_func(self,path,sg_publish_data):

        # file_node = cmds.shadingNode('file', asTexture=True)
        file_node = mel.eval('createRenderNodeCB -as2DTexture "" "file" "";')
        cmds.setAttr("%s.fileTextureName" % file_node, path, type="string")
        return file_node

    def _create_udim_texture_node(self, path, sg_publish_data):
        """
        Create a file texture node for a UDIM (Mari) texture
        
        :param path:             Path to file.
        :param sg_publish_data:  Shotgun data dictionary with all the standard publish fields.
        :returns:                The newly created file node
        """
        # create the normal file node:
        file_node = self._create_texture_node_func(path, sg_publish_data)
        if file_node:
            # path is a UDIM sequence so set the uv tiling mode to 3 ('UDIM (Mari)')
            cmds.setAttr("%s.uvTilingMode" % file_node, 3)
            # ---------set preview quality-----:
            cmds.setAttr("%s.uvTileProxyQuality" % file_node, 4)
            # set color space
            srgb_color = ["Diffuse","Reflection"]
            raw_color = ["Glossiness","IOR","Normal"]
            for srgb in srgb_color:
                if re.search(srgb,file_node,re.IGNORECASE):
                    cmds.setAttr("%s.colorSpace"%file_node,"sRGB",type = "string")

            for raw in raw_color:
                if re.search(raw,file_node,re.IGNORECASE):
                    cmds.setAttr("%s.colorSpace"%file_node,"Raw",type = "string")

            # and generate a preview:
            mel.eval("generateUvTilePreview %s" % file_node)
        return file_node
    
    # create texture node by texture folder:
    def _create_texture_nodes_byfolder(self,path,sg_publish_data):
        """
        Create file texture nodes from texture folder
        :returns:       file nodes list
        """
        _files = os.listdir(path)
        full_file_name =[]
        json_file = ''
        other_file = []
        for _file in _files:
            _file_full_name = path + '\\' +_file
            full_file_name.append(_file_full_name)
            name,ext = os.path.splitext(_file_full_name)
            if not ext:
                other_file.append(_file_full_name)
            elif ext == ".obj":
                other_file.append(_file_full_name)
            elif ext == ".mtl":
                other_file.append(_file_full_name)
            elif ext == '.json':
                json_file = _file_full_name
                other_file.append(json_file)
            else:
                continue
        if not json_file:
            return
        for otf in other_file:
            full_file_name.remove(otf)
        with open(json_file,'r') as f:
            _data = json.load(f)
        texturesets = _data.get("texturesets")
        if not texturesets:
            return
        k = texturesets.keys()[0]
        try:
            temp = int(k)
            config = "UDIM"
        except ValueError, e:
            config = "Texture"
        file_nodes = []
        if config == "UDIM":
            for image_file in full_file_name:
                if re.match(".+(1001\.[a-z].+)", image_file):
                    file_nodes.append(self._create_udim_texture_node(image_file,sg_publish_data))
        elif config == "Texture":
            for image_file in full_file_name:
                file_nodes.append(self._create_texture_node_func(image_file,sg_publish_data))
        return file_nodes



    def _create_image_plane(self, path, sg_publish_data):
        """
        Create a file texture node for a UDIM (Mari) texture

        :param path: Path to file.
        :param sg_publish_data: Shotgun data dictionary with all the standard
            publish fields.
        :returns: The newly created file node
        """

        app = self.parent
        has_frame_spec = False

        # replace any %0#d format string with a glob character. then just find
        # an existing frame to use. example %04d => *
        frame_pattern = re.compile("(%0\dd)")
        frame_match = re.search(frame_pattern, path)
        if frame_match:
            has_frame_spec = True
            frame_spec = frame_match.group(1)
            glob_path = path.replace(frame_spec, "*")
            frame_files = glob.glob(glob_path)
            if frame_files:
                path = frame_files[0]
            else:
                app.logger.error(
                    "Could not find file on disk for published file path %s" %
                    (path,)
                )
                return

        # create an image plane for the supplied path, visible in all views
        (img_plane, img_plane_shape) = cmds.imagePlane(
            fileName=path,
            showInAllViews=True
        )
        app.logger.debug(
            "Created image plane %s with path %s" %
            (img_plane, path)
        )

        if has_frame_spec:
            # setting the frame extension flag will create an expression to use
            # the current frame.
            cmds.setAttr("%s.useFrameExtension" % (img_plane_shape,), 1)

    def _get_maya_version(self):
        """
        Determine and return the Maya version as an integer
        
        :returns:    The Maya major version
        """
        if not hasattr(self, "_maya_major_version"):
            self._maya_major_version = 0
            # get the maya version string:
            maya_ver = cmds.about(version=True)
            # handle a couple of different formats: 'Maya XXXX' & 'XXXX':
            if maya_ver.startswith("Maya "):
                maya_ver = maya_ver[5:]
            # strip of any extra stuff including decimals:
            major_version_number_str = maya_ver.split(" ")[0].split(".")[0]
            if major_version_number_str and major_version_number_str.isdigit():
                self._maya_major_version = int(major_version_number_str)
        return self._maya_major_version

    def _load_render_setting(self,preset_name,path):
        from __Maya.lighting._self import renderSettingManage
        reload(renderSettingManage)
        renderSettingManage.load_render_setting(preset_name, path)


# def _hookup_shaders(reference_node):
#     """
#     Reconnects published shaders to the corresponding mesh.
#     :return:
#     """
#
#     # find all shader hookup script nodes and extract the mesh object info
#     # print "reference node:", reference_node
#     hookup_prefix = "SHADER_HOOKUP_"
#     shader_hookups = {}
#     for node in cmds.ls(type="script"):
#         node_parts = node.split(":")
#         node_base = node_parts[-1]
#         node_namespace = ":".join(node_parts[:-1])
#         if not node_base.startswith(hookup_prefix):
#             continue
#         obj_pattern = node_base.replace(hookup_prefix, "") + "\d*"
#         obj_pattern = "^" + obj_pattern + "$"
#         shader = cmds.scriptNode(node, query=True, beforeScript=True)
#         shader_hookups[obj_pattern] = node_namespace + ":" + shader
#
#     # if the object name matches an object in the file, connect the shaders
#     for node in (cmds.ls(references=True, transforms=True) or []):
#         for (obj_pattern, shader) in shader_hookups.iteritems():
#             # get rid of namespacing
#             node_base = node.split(":")[-1]
#             if re.match(obj_pattern, node_base, re.IGNORECASE):
#                 # assign the shader to the object
#                 if not cmds.objExists(shader):
#                     continue
#                 cmds.select(node, replace=True)
#                 cmds.hyperShade(assign=shader)
def _shader_hookup_data(hookup_prefix):
    shader_hookups = {}  # {geo:shader}
    for node in cmds.ls(type="script"):
        node_parts = node.split(":")
        node_base = node_parts[-1]
        node_namespace = ":".join(node_parts[:-1])
        if not node_base.startswith(hookup_prefix):
            continue
        obj_pattern = node_base.replace(hookup_prefix, "")  # + "\d*"
        obj_pattern = "^" + obj_pattern + "$"
        shader = cmds.scriptNode(node, query=True, beforeScript=True)
        shader_hookups[obj_pattern] = node_namespace + ":" + shader

    return shader_hookups
def _hookup_shaders(hookup_prefix,node_type,collection = None):

    # find all shader hookup script nodes and extract the mesh object info
    # print "reference node:", reference_node
    # hookup_prefix = "SHADER_HOOKUP_"
    shader_hookups = _shader_hookup_data(hookup_prefix)
    # if the object name matches an object in the file, connect the shaders
    if node_type == "mesh":
        nodes = cmds.ls(transforms=True) or []
    elif node_type == "xgmDescription":
        try:
            import xgenm as xg
        except Exception, e:
            raise Exception(e)
        if collection is None:
            raise Exception("The keyword 'collection' is None!")
        nodes = xg.descriptions(collection)

    for node in nodes:
        node_shape = cmds.listRelatives(node, type=node_type, c=True)
        if not node_shape:
            continue
        node_base = node.split(":")[-1]
        node_long_name = cmds.ls(node, l=True)[0]
        sp = node_long_name.split("|")
        node_temp = None
        node_parents = sp[:-1]
        node_parent_base_list = []
        for pa in node_parents:
            if pa == "":
                continue
            node_parent_base_list.append(pa.split(":")[-1])
        node_parent_base_list.append(node_base)
        node_temp = "_".join(node_parent_base_list)

        for (obj_pattern, shader) in shader_hookups.iteritems():
            if re.search(obj_pattern, node_temp, re.IGNORECASE):
                # assign the shader to the object
                # print obj_pattern,node_temp
                if not cmds.objExists(shader):
                    continue
                cmds.select(node, replace=True)
                cmds.hyperShade(assign=shader)
def _hookup_xgen(path):

    try:
        import xgenm as xg
        import xgenm.ui.dialogs.xgImportFile as xif

    except Exception, e:
        raise Exception(e)
    from func import cfaXgenAPI
    from func import replace_special_character as rsc
    from cfa_widgets import CFAUI
    from cfa_widgets import *
    import shutil
    work_file = cmds.file(q=True, sn=True)
    if not work_file:
        CFAUI.messageBox("Please save the file first!")
        return
    current_dir = os.path.dirname(work_file)
    # all_files = os.listdir(current_dir)
    # if "xgen" in all_files:
    #     shutil.rmtree(current_dir + "/xgen")
    basename = os.path.basename(path)
    collection = (basename.split('__')[-1]).split('.')[0]
    collection_path = current_dir + "/xgen/collections/" +collection
    if os.path.isdir(collection_path):
        ret = CFAUI.warningBox("---%s--- already exists in \n\t Will you delete it and continue?" % (collection_path))
        if ret == QMessageBox.Ok:
            shutil.rmtree(collection_path)
        else:
            return False
    path = rsc.replaceSpecialCharacter(path)
    print "xgen-path:", path
    validator = xif.Validator(xg.ADD_TO_NEW_PALETTE, None)
    cfaXgenAPI.importBindPalette(str(path), '', validator, True)

    palettes = xg.palettes()
    for palette in palettes:
        descriptions = list(xg.descriptions(str(palette)))
        try:
            mel.eval('xgmDensityComp -f -pb {"%s"};' % descriptions[-1])
        except:
            pass
    return True
def _hookup_simcrv(path):
    try:
        import xgenm as xg
        import xgenm.xgGlobal as xgg
    except Exception, e:
        raise Exception(e)
    from func import replace_special_character as rsc
    path = str(rsc.replaceSpecialCharacter(path))
    basename = os.path.basename(path)
    _SIMCRV = "_SIMCRV"

    description = str(basename.split(_SIMCRV)[0])
    palette = str(xg.palette(description))
    _object_type = str(xg.objects(palette, description)[2])
    de = xgg.DescriptionEditor
    # use cache
    xg.setAttr(
        str("useCache"),
        str("1"),
        palette,
        description,
        _object_type
    )
    # live mode :0
    xg.setAttr(
        str("liveMode"),
        str("0"),
        palette,
        description,
        _object_type
    )
    xg.setAttr(
        str("cacheFileName"),
        path,
        palette,
        description,
        _object_type
    )

    de.update()
def update_scene_time():
    from func import shotgun_func
    shotgun_func.update_scene_time()
def update_resolution():
    from __Maya.common import maya_func
    maya_func.setResolution()