# Copyright (c) 2017 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.

import glob
import os
import re
import maya.cmds as cmds
import maya.mel as mel
import sgtk
from sgtk.util import shotgun
HookBaseClass = sgtk.get_hook_baseclass()
ISASSEMBLY = False
class MayaSessionCollector(HookBaseClass):
    """
    Collector that operates on the maya session. Should inherit from the basic
    collector hook.
    """

    @property
    def settings(self):
        """
        Dictionary defining the settings that this collector expects to receive
        through the settings parameter in the process_current_session and
        process_file methods.

        A dictionary on the following form::

            {
                "Settings Name": {
                    "type": "settings_type",
                    "default": "default_value",
                    "description": "One line description of the setting"
            }

        The type string should be one of the data types that toolkit accepts as
        part of its environment configuration.
        """

        # grab any base class settings
        collector_settings = super(MayaSessionCollector, self).settings or {}

        # settings specific to this collector
        maya_session_settings = {
            "Work Template": {
                "type": "template",
                "default": None,
                "description": "Template path for artist work files. Should "
                               "correspond to a template defined in "
                               "templates.yml. If configured, is made available"
                               "to publish plugins via the collected item's "
                               "properties. ",
            },
        }

        # update the base settings with these settings
        collector_settings.update(maya_session_settings)

        return collector_settings

    def process_current_session(self, settings, parent_item):
        """
        Analyzes the current session open in Maya and parents a subtree of
        items under the parent_item passed in.

        :param dict settings: Configured settings for this collector
        :param parent_item: Root item instance

        """
        path = cmds.file(query=True, sn=True)
        if not path:
            em = "Please save the scene first."
            self.logger.error(em)
            raise Exception(em)
        filename = os.path.basename(path)
        isProxy = False
        if "RSProxyRig" in filename:
            isProxy = True

        # create an item representing the current maya session
        item = self.collect_current_maya_session(settings, parent_item)
        project_root = item.properties["project_root"]
        context = item.context
        # self.logger.debug("collector:session----%s----" % context)
        self.logger.debug("collector:session----%s----" % context.task)
        # look at the render layers to find rendered images on disk
        self.collect_rendered_images(item)
        step_id = context.step.get('id')
        # self.logger.debug("step_id:---%s---" % step_id)
        # if we can determine a project root, collect other files to publish
        if project_root:
            self.logger.info(
                "Current Maya project is: %s." % (project_root,),
                extra={
                    "action_button": {
                        "label": "Change Project",
                        "tooltip": "Change to a different Maya project",
                        "callback": lambda: mel.eval('setProject ""')
                    }
                }
            )
            # self.collect_playblasts(item, project_root)
            if step_id == 138:
                self._collect_xgen(item, project_root)
                self._collect_xgen_shader(item)
                self._collect_xgen_geometry(item)
        else:
            self.logger.info(
                "Could not determine the current Maya project.",
                extra={
                    "action_button": {
                        "label": "Set Project",
                        "tooltip": "Set the Maya project",
                        "callback": lambda: mel.eval('setProject ""')
                    }
                }
            )

        if step_id in [106,35]:
            self._collect_cameras(item)
        if step_id in[15]:
            if not isProxy:
                self._collect_meshes(item)
        # if step_id in [14,15]:
        #     self._collect_assembly(item)
        if step_id in [16,136]:
            self._collect_fbx_geometry(item)
            # self._collect_uvmap(item)
        if step_id in [143]:
            self._collect_simcrv(item)
        self._collect_lightrig(item)
        # print "ISASSEMBLY:",ISASSEMBLY
        if step_id not in [138,150,155]:
            if cmds.ls(geometry=True, noIntermediate=True):
                # if not ISASSEMBLY:
                if not isProxy:
                    self._collect_session_geometry(item)
        if project_root:
            # if not ISASSEMBLY:
            if not isProxy:
                self.collect_alembic_caches(item, project_root)



    def collect_current_maya_session(self, settings, parent_item):
        """
        Creates an item that represents the current maya session.

        :param parent_item: Parent Item instance

        :returns: Item of type maya.session
        """

        publisher = self.parent

        # get the path to the current file
        path = cmds.file(query=True, sn=True)

        # determine the display name for the item
        if path:
            file_info = publisher.util.get_file_path_components(path)
            display_name = file_info["filename"]
        else:
            display_name = "Current Maya Session"

        # create the session item for the publish hierarchy
        session_item = parent_item.create_item(
            "maya.session",
            "Maya Session",
            display_name
        )

        # get the icon path to display for this item
        icon_path = os.path.join(
            self.disk_location,
            os.pardir,
            "icons",
            "maya.png"
        )
        session_item.set_icon_from_path(icon_path)

        # discover the project root which helps in discovery of other
        # publishable items
        project_root = cmds.workspace(q=True, rootDirectory=True)
        session_item.properties["project_root"] = project_root

        # if a work template is defined, add it to the item properties so
        # that it can be used by attached publish plugins
        work_template_setting = settings.get("Work Template")
        if work_template_setting:

            work_template = publisher.engine.get_template_by_name(
                work_template_setting.value)

            # store the template on the item for use by publish plugins. we
            # can't evaluate the fields here because there's no guarantee the
            # current session path won't change once the item has been created.
            # the attached publish plugins will need to resolve the fields at
            # execution time.
            session_item.properties["work_template"] = work_template
            self.logger.debug("Work template defined for Maya collection.")

        self.logger.info("Collected current Maya scene")

        return session_item

    def collect_alembic_caches(self, parent_item, project_root):
        """
        Creates items for alembic caches

        Looks for a 'project_root' property on the parent item, and if such
        exists, look for alembic caches in a 'cache/alembic' subfolder.

        :param parent_item: Parent Item instance
        :param str project_root: The maya project root to search for alembics
        """

        # ensure the alembic cache dir exists
        # print "parent_item:",parent_item.to_dict()


        # modify abc folder like this: .../cache/alembic/{shot_name}

        # publisher = self.parent
        #
        # # get the path to the current file
        # path = cmds.file(query=True, sn=True)
        #
        # # determine the display name for the item
        # if path:
        #     shot_version_name = getCurrentShotName(path)
        # else:
        #     shot_version_name = "untitled"
        # cache_dir = os.path.join(project_root, "cache", "alembic",shot_version_name)
        # if not os.path.exists(cache_dir):
        #     return
        #
        # self.logger.info(
        #     "Processing alembic cache folder: %s" % (cache_dir,),
        #     extra={
        #         "action_show_folder": {
        #             "path": cache_dir
        #         }
        #     }
        # )
        from func import shotgun_func,_shotgun_server,replace_special_character as rsc
        reload(shotgun_func)
        scene_data = shotgun_func.getSceneSGData()
        current_id = scene_data.get('entity').get('id')
        current_entity_type = scene_data.get('entity').get('type')
        sg = _shotgun_server._shotgun()
        publish_files = sg.find("PublishedFile", [['entity.%s.id'%current_entity_type, 'is', current_id]],
                                ['published_file_type', 'path'])
        abc_publish_files = []
        for pf in publish_files:
            if pf.get('published_file_type').get('name') == "Alembic Cache":
                _path = pf.get('path').get('local_path_windows')
                if "\\cache\\alembic" not in _path:
                    continue
                if  _path not in abc_publish_files:
                    abc_publish_files.append(rsc.replaceSpecialCharacter(_path))
        print abc_publish_files
        cache_dir = os.path.join(project_root, "cache", "alembic")
        if not os.path.exists(cache_dir):
            return

        self.logger.info(
            "Processing alembic cache folder: %s" % (cache_dir,),
            extra={
                "action_show_folder": {
                    "path": cache_dir
                }
            }
        )

        # look for alembic files in the cache folder
        for filename in os.listdir(cache_dir):
            cache_path = os.path.join(cache_dir, filename)
            cache_path = rsc.replaceSpecialCharacter(cache_path)
            # do some early pre-processing to ensure the file is of the right
            # type. use the base class item info method to see what the item
            # type would be.
            item_info = self._get_item_info(filename)
            if item_info["item_type"] != "file.alembic":
                continue
            if cache_path in abc_publish_files:
                continue

            # allow the base class to collect and create the item. it knows how
            # to handle alembic files
            item = super(MayaSessionCollector, self)._collect_file(
                parent_item,
                cache_path
            )
            item._expanded = False
            item._active = True
    def _collect_session_geometry(self, parent_item):
        """
        Creates items for session geometry to be exported.

        :param parent_item: Parent Item instance
        """

        geo_item = parent_item.create_item(
            "maya.session.geometry",
            "Geometry",
            "All Session Geometry"
        )

        # get the icon path to display for this item
        icon_path = os.path.join(
            self.disk_location,
            os.pardir,
            "icons",
            "geometry.png"
        )

        geo_item.set_icon_from_path(icon_path)
        geo_item._expanded = False
        # geo_item._active = False

    def collect_playblasts(self, parent_item, project_root):
        """
        Creates items for quicktime playblasts.

        Looks for a 'project_root' property on the parent item, and if such
        exists, look for movie files in a 'movies' subfolder.

        :param parent_item: Parent Item instance
        :param str project_root: The maya project root to search for playblasts
        """

        movie_dir_name = None

        # try to query the file rule folder name for movies. This will give
        # us the directory name set for the project where movies will be
        # written
        if "movie" in cmds.workspace(fileRuleList=True):
            # this could return an empty string
            movie_dir_name = cmds.workspace(fileRuleEntry='movie')

        if not movie_dir_name:
            # fall back to the default
            movie_dir_name = "movies"

        # ensure the movies dir exists
        movies_dir = os.path.join(project_root, movie_dir_name)
        if not os.path.exists(movies_dir):
            return

        self.logger.info(
            "Processing movies folder: %s" % (movies_dir,),
            extra={
                "action_show_folder": {
                    "path": movies_dir
                }
            }
        )

        # look for movie files in the movies folder
        # get max version file:
        import re
        version = 0
        max_file = ""
        pattern = "\w+_[A-Za-z]+\.v\d+\.mov"
        pattern2 = "\w+_[A-Za-z]+\.v(\d+)\.mov"
        for filename in os.listdir(movies_dir):
            item_info = self._get_item_info(filename)
            if item_info["item_type"] != "file.video":
                continue
            if re.match(pattern, filename):
                num = int(re.findall(pattern2,filename)[0])
                if num >version:
                    version = num
                    max_file = filename

        if not max_file:
            return
        max_file_path = os.path.join(movies_dir,max_file)

        item = super(MayaSessionCollector, self)._collect_file(
            parent_item,
            max_file_path
        )

        # the item has been created. update the display name to include
        # the an indication of what it is and why it was collected
        item.name = os.path.splitext(max_file)[0]
        item.name = "%s (%s)" % (item.name, "playblast")
        item._expanded = False
        # item._active = False

    def collect_rendered_images(self, parent_item):
        """
        Creates items for any rendered images that can be identified by
        render layers in the file.

        :param parent_item: Parent Item instance
        :return:
        """
        scene = cmds.file(q=True, sn=True)
        basename = os.path.basename(scene)
        _name, ext = os.path.splitext(basename)
        work_dir = cmds.workspace(q=True, sn=True)
        image_dir = work_dir + '/images'

        # get a list of render layers not defined in the file
        render_layers = []
        _render = cmds.getAttr("defaultRenderGlobals.currentRenderer")
        # _prefix = cmds.getAttr("vraySettings.fileNamePrefix")
        for layer_node in cmds.ls(type="renderLayer"):
            try:
                # if this succeeds, the layer is defined in a referenced file
                cmds.referenceQuery(layer_node, filename=True)
            except RuntimeError:
                # runtime error means the layer is defined in this session
                render_layers.append(layer_node)

        # iterate over defined render layers and query the render settings for
        # information about a potential render
        for layer in render_layers:

            self.logger.info("Processing render layer: %s" % (layer,))

            # use the render settings api to get a path where the frame number
            # spec is replaced with a '*' which we can use to glob
            (frame_glob,) = cmds.renderSettings(
                genericFrameImageName="*",
                fullPath=True,
                layer=layer
            )
            if _render == "vray":
                try:

                    mel.eval("unifiedRenderGlobalsWindow;")
                    cmds.workspaceControl("unifiedRenderGlobalsWindow", e=True, vis=0, r=True)
                    fileprefix = cmds.getAttr('vraySettings.fileNamePrefix')
                    _image_format = cmds.getAttr("vraySettings.imageFormatStr")
                    if fileprefix == '<Scene>/<Layer>/<Scene>':
                        image_file = image_dir + '/' + _name + '/' + layer + '/' + _name + '*.%s'%_image_format
                        frame_glob = image_file
                except:
                    pass
            # see if there are any files on disk that match this pattern
            rendered_paths = glob.glob(frame_glob)
            self.logger.debug( "rendered_paths: ----%s----"%rendered_paths)
            if rendered_paths:
                # we only need one path to publish, so take the first one and
                # let the base class collector handle it
                item = super(MayaSessionCollector, self)._collect_file(
                    parent_item,
                    rendered_paths[0],
                    frame_sequence=True
                )

                # the item has been created. update the display name to include
                # the an indication of what it is and why it was collected
                item.name = "%s (Render Layer: %s)" % (item.name, layer)
                item._expanded = False
                item._active = False

    def _collect_meshes(self, parent_item):
        """
        Collect mesh definitions and create publish items for them.

        :param parent_item: The maya session parent item
        """

        # build a path for the icon to use for each item. the disk
        # location refers to the path of this hook file. this means that
        # the icon should live one level above the hook in an "icons"
        # folder.
        icon_path = os.path.join(
            self.disk_location,
            os.pardir,
            "icons",
            "mesh.png"
        )

        # iterate over all top-level transforms and create mesh items
        # for any mesh.
        context = parent_item.context

        for object in cmds.ls(assemblies=True):

            if not cmds.ls(object, dag=True, type="mesh"):
                # ignore non-meshes
                continue

            # create a new item parented to the supplied session item. We
            # define an item type (maya.session.mesh) that will be
            # used by an associated shader publish plugin as it searches for
            # items to act upon. We also give the item a display type and
            # display name (the group name). In the future, other publish
            # plugins might attach to these mesh items to publish other things

            # object = object.replace(":","_")
            mesh_item = parent_item.create_item(
                "maya.session.mesh",
                "Shader",
                object
            )

            # set the icon for the item
            mesh_item.set_icon_from_path(icon_path)

            # finally, add information to the mesh item that can be used
            # by the publish plugin to identify and export it properly
            mesh_item.properties["object"] = object

            mesh_item._expanded = False
            mesh_item._active = False
            # if step is shading , active is True.
            if context.step.get('id') == 15:
                mesh_item._active = True

    def _collect_cameras(self, parent_item):
        """
        Creates items for each camera in the session.

        :param parent_item: The maya session parent item
        """

        # build a path for the icon to use for each item. the disk
        # location refers to the path of this hook file. this means that
        # the icon should live one level above the hook in an "icons"
        # folder.

        self.logger.debug("Camera publish...")
        icon_path = os.path.join(
            self.disk_location,
            os.pardir,
            "icons",
            "camera.png"
        )

        # iterate over each camera and create an item for it
        for camera_shape in cmds.ls(cameras=True):

            # try to determine the camera display name
            try:
                camera_name = cmds.listRelatives(camera_shape, parent=True)[0]
            except Exception:
                # could not determine the name, just use the shape
                camera_name = camera_shape

            # create a new item parented to the supplied session item. We
            # define an item type (maya.session.camera) that will be
            # used by an associated camera publish plugin as it searches for
            # items to act upon. We also give the item a display type and
            # display name. In the future, other publish plugins might attach to
            # these camera items to perform other actions
            cam_item = parent_item.create_item(
                "maya.session.camera",
                "Camera",
                camera_name
            )

            # set the icon for the item
            cam_item.set_icon_from_path(icon_path)

            # store the camera name so that any attached plugin knows which
            # camera this item represents!
            cam_item.properties["camera_name"] = camera_name
            cam_item.properties["camera_shape"] = camera_shape


    def _collect_uvmap(self,parent_item):

        # if the step is uv ,display these items

        self.logger.info("uv map publish...")
        icon_path = os.path.join(
            self.disk_location,
            os.pardir,
            "icons",
            "uvmap.png"
        )

        objects = set()
        meshs = cmds.ls(type="mesh")
        for m in meshs:
            parent = cmds.listRelatives(m, p=True)[0]
            # parent = parent.replace(":", "_")
            # parent = parent.replace("_", "")
            objects.add(parent)

        for obj in objects:
            uv_item = parent_item.create_item(
                "maya.session.uvmap",
                "UVMap",
                obj
            )

            uv_item.set_icon_from_path(icon_path)
            uv_item.properties["uvmap_name"] = obj
            file_name = obj.replace(":","_")
            uv_item.properties["uvmap_file_name"] = file_name

            uv_item._expanded = False
            # uv_item._active = False

    def _collect_xgen(self,parent_item, project_root):

        try:
            import xgenm as xg
        except Exception,e:
            self.logger.debug(e)
            return
        self.logger.debug("XGen publish...")
        icon_path = os.path.join(
            self.disk_location,
            os.pardir,
            "icons",
            "xgen.png"
        )
        # check xgmPalette node in scene
        collections = xg.palettes()
        if not collections:
            return
        xgen_dir_name = "xgen/collections"
        xgen_dir = os.path.join(project_root, xgen_dir_name)
        if not os.path.exists(xgen_dir):
            return

        self.logger.info(
            "Processing xgen folder: %s" % (xgen_dir,),
            extra={
                "action_show_folder": {
                    "path": xgen_dir
                }
            }
        )
        for collection in collections:
            collection_path = os.path.join(xgen_dir, collection)
            self.logger.debug("collection:%s"%collection)
            if not os.path.isdir(collection_path):
                continue
            xgen_item = parent_item.create_item(
                "maya.session.xgen",
                "XGen",
                collection
            )

            # xgen_item.name = "%s (%s)" % (xgen_item.name, "XGen")
            xgen_item.set_icon_from_path(icon_path)
            xgen_item.properties['collection_path'] = collection_path
            xgen_item.properties['collection'] = collection

            xgen_item._expanded = False
            # item._active = False

    def _collect_xgen_shader(self, parent_item):
        try:
            import xgenm as xg
        except Exception,e:
            self.logger.debug(e)
            return
        icon_path = os.path.join(
            self.disk_location,
            os.pardir,
            "icons",
            "XGen.png"
        )

        for collection in xg.palettes():

            xgen_item = parent_item.create_item(
                "maya.session.xgshader",
                "XGen Shader",
                collection+"_Shader"
            )
            # set the icon for the item
            xgen_item.set_icon_from_path(icon_path)

            xgen_item.properties["collection"] = collection

            xgen_item._expanded = False
            xgen_item._active = True

    def _collect_xgen_geometry(self,parent_item):
        try:
            import xgenm as xg
        except Exception,e:
            self.logger.debug(e)
            return
        icon_path = os.path.join(
            self.disk_location,
            os.pardir,
            "icons",
            "XGen.png"
        )

        collection = xg.palettes()[0]
        xg_geometry = set()
        for descriptions in xg.descriptions(collection):
            geometry = xg.boundGeometry(collection,descriptions)
            for geo in geometry :
                xg_geometry.add(geo)
        _geometry = list(xg_geometry)
        self.logger.debug("XGen Geometry:%s"%_geometry)
        _geometry_grp = cmds.listRelatives(_geometry[0],parent = True)[0]


        xgen_item = parent_item.create_item(
            "maya.session.xggeometry",
            "XGen Geometry",
            _geometry_grp
        )
        # set the icon for the item
        xgen_item.set_icon_from_path(icon_path)

        xgen_item.properties["geometry"] = _geometry_grp

        xgen_item._expanded = False
        xgen_item._active = True
        # for geo in list(_geometry):
        #     xgen_item = parent_item.create_item(
        #         "maya.session.xggeometry",
        #         "XGen Geometry",
        #         geo
        #     )
        #     # set the icon for the item
        #     xgen_item.set_icon_from_path(icon_path)
        #
        #     xgen_item.properties["geometry"] = geo
        #
        #     xgen_item._expanded = False
        #     xgen_item._active = True

    def _collect_fbx_geometry(self, parent_item):
        """
        Creates items for session geometry to be exported.

        :param parent_item: Parent Item instance
        """
        self.logger.debug('fbx collector...')
        icon_path = os.path.join(
            self.disk_location,
            os.pardir,
            "icons",
            "fbx.jpg"
        )

        # iterate over all top-level transforms and create mesh items
        # for any mesh.

        for object in cmds.ls(assemblies=True):

            if not cmds.ls(object, dag=True, type="mesh"):
                # ignore non-meshes
                continue
            print "object is %s:",object

            # create a new item parented to the supplied session item. We
            # define an item type (maya.session.mesh) that will be
            # used by an associated shader publish plugin as it searches for
            # items to act upon. We also give the item a display type and
            # display name (the group name). In the future, other publish
            # plugins might attach to these mesh items to publish other things

            # object = object.replace(":","_")
            mesh_item = parent_item.create_item(
                "maya.fbx.geometry",
                "FBXGeometry",
                object
            )

            # set the icon for the item
            mesh_item.set_icon_from_path(icon_path)

            # finally, add information to the mesh item that can be used
            # by the publish plugin to identify and export it properly
            mesh_item.properties["object"] = object

            mesh_item._expanded = False
            mesh_item._active = True
            # if step is shading , active is True.
            # if context.step.get('id') in [16,136]:
            #     mesh_item._active = True

    def _collect_lightrig(self,parent_item):
        self.logger.debug('lightrig collector...')
        icon_path = os.path.join(
            self.disk_location,
            os.pardir,
            "icons",
            "lightrig.png"
        )

        # iterate over all top-level transforms and create mesh items
        # for any mesh.
        lightRig = None
        context = parent_item.context
        entity_name = context.entity.get('name')
        entity_name = entity_name.replace('_','')
        for object in cmds.ls(assemblies=True):

            if re.match(entity_name + '_lightRig_',object):
                lightRig = object
                break
        if lightRig is not None:
            mesh_item = parent_item.create_item(
                "maya.session.lightrig",
                "LightRig",
                lightRig
            )

            # set the icon for the item
            mesh_item.set_icon_from_path(icon_path)

            # finally, add information to the mesh item that can be used
            # by the publish plugin to identify and export it properly
            mesh_item.properties["lightRig"] = lightRig

            mesh_item._expanded = False
            mesh_item._active = True
        else:
            self.logger.debug('No lightrig exists.')

    def _collect_simcrv(self,parent_item):
        self.logger.debug('simCurve collector...')
        icon_path = os.path.join(
            self.disk_location,
            os.pardir,
            "icons",
            "XGen.png"
        )

        # iterate over all top-level transforms and create mesh items
        # for any mesh.
        _simcrv_list = cmds.ls("*_SIMCRV")
        if not _simcrv_list:
            return
        for simcrv in _simcrv_list:

            mesh_item = parent_item.create_item(
                "maya.session.simcrv",
                "SimCurve",
                simcrv
            )

            # set the icon for the item
            mesh_item.set_icon_from_path(icon_path)

            # finally, add information to the mesh item that can be used
            # by the publish plugin to identify and export it properly
            mesh_item.properties["simCrvName"] = simcrv

            mesh_item._expanded = False
            mesh_item._active = True
    def _collect_assembly(self,parent_item):
        self.logger.debug('assembly collector...')
        global ISASSEMBLY
        all_objects = cmds.ls(assemblies=True)
        _assembly_objects = []
        other_objects = []
        for ao in all_objects:
            if cmds.objectType(ao) == "assemblyDefinition":
                _assembly_objects.append(ao)
            elif cmds.objectType(ao) == "assemblyReference":
                _assembly_objects.append(ao)
            else:
                other_objects.append(ao)
        if not _assembly_objects:
            ISASSEMBLY = False
            return
        else:
            ISASSEMBLY = True
        mesh_objects = []
        for obj in other_objects:
            mesh = cmds.ls(obj,dag = True,type="mesh")
            if mesh:
                mesh_objects.append(mesh)
        if mesh_objects:
            return
        ad = cmds.ls(type="assemblyDefinition")
        ar = cmds.ls(type="assemblyReference")
        if ad and ar:
            emg = "AssemblyDefinition and assemblyReference,two types of nodes, only one can exist with an assembly asset."
            self.logger.debug(emg)
            return
        icon_path = os.path.join(
            self.disk_location,
            os.pardir,
            "icons",
            "maya.png"
        )
        ISASSEMBLY = True
        _assembly_objects_str = ';'.join(_assembly_objects)
        assembly_item = parent_item.create_item(
            "maya.session.assembly",
            "Assembly",
            _assembly_objects[0] + '...'
        )
        assembly_item.set_icon_from_path(icon_path)
        assembly_item.properties['assemblyName'] = _assembly_objects_str
        assembly_item._expanded = False
        assembly_item._active = True
def getCurrentShotName(scene_path):
    '''

    :param scene_path:
    :return: shot name with a version
    '''
    basename = os.path.basename(scene_path)
    sp = basename.split(".")[:-1]
    name = ".".join(sp)
    return name
def _shotgun():
    sg = shotgun.create_sg_connection()
    return sg