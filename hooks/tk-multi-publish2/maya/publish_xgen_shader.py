# Copyright (c) 2017 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import re
import maya.cmds as cmds
import sgtk


# this method returns the evaluated hook base class. This could be the Hook
# class defined in Toolkit core or it could be the publisher app's base publish
# plugin class as defined in the configuration.
HookBaseClass = sgtk.get_hook_baseclass()


class MayaXGenShaderPublishPlugin(HookBaseClass):
    """
    This class defines the required interface for a publish plugin. Publish
    plugins are responsible for operating on items collected by the collector
    plugin. Publish plugins define which items they will operate on as well as
    the execution logic for each phase of the publish process.
    """

    ############################################################################
    # Plugin properties

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does (:class:`str`).

        The string can contain html for formatting for display in the UI (any
        html tags supported by Qt's rich text engine).
        """
        return """
        <p>
        This plugin handles exporting and publishing Maya xgen shader networks.
        Collected xgen shaders are exported to disk as .ma files that can
        be loaded by artists downstream. This is a simple, example
        implementation and not meant to be a robust, battle-tested solution for
        shader or texture management on production.
        </p>
        """

    @property
    def settings(self):

        plugin_settings = super(MayaXGenShaderPublishPlugin, self).settings or {}

        # settings specific to this class
        shader_publish_settings = {
            "Publish Template": {
                "type": "template",
                "default": None,
                "description": "Template path for published shader networks. "
                               "Should correspond to a template defined in "
                               "templates.yml.",
            }
        }

        # update the base settings
        plugin_settings.update(shader_publish_settings)

        return plugin_settings

    @property
    def item_filters(self):

        return ["maya.session.xgshader"]

    ############################################################################
    # Publish processing methods

    def accept(self, settings, item):
        accepted = True

        # a handle on the instance of the publisher app
        publisher = self.parent

        # extract the value of the template configured for this instance
        template_name = settings["Publish Template"].value

        # ensure a work file template is available on the parent maya session
        # item.
        work_template = item.parent.properties.get("work_template")
        if not work_template:
            self.logger.debug(
                "A work template is required for the session item in order to "
                "publish session geometry. Not accepting session geom item."
            )
            accepted = False

        # ensure the publish template is defined and valid
        publish_template = publisher.get_template_by_name(template_name)
        self.logger.debug("TEMPLATE NAME: " + str(template_name))
        if not publish_template:
            self.logger.debug(
                "A valid publish template could not be determined for the "
                "session geometry item. Not accepting the item."
            )
            accepted = False

        # we've validated the publish template. add it to the item properties
        # for use in subsequent methods
        item.properties["publish_template"] = publish_template

        # because a publish template is configured, disable context change. This
        # is a temporary measure until the publisher handles context switching
        # natively.
        item.context_change_allowed = False

        return {
            "accepted": accepted,
            "checked": True
        }

    def validate(self, settings, item):

        path = _session_path()

        # self.logger.debug("context:----%s----"%item.context)
        # self.logger.debug("task:----%s----" % item.context.task)

        # ---- ensure the session has been saved

        if not path:
            # the session still requires saving. provide a save button.
            # validation fails.
            error_msg = "The Maya session has not been saved."
            self.logger.error(
                error_msg,
                extra=_get_save_as_action()
            )
            raise Exception(error_msg)

        # get the normalized path. checks that separators are matching the
        # current operating system, removal of trailing separators and removal
        # of double separators, etc.
        path = sgtk.util.ShotgunPath.normalize(path)

        collection_name = item.properties["collection"]
        self.logger.debug("collection_name:%s"%collection_name)
        # check that there is still geometry in the scene:
        if (not cmds.ls(collection_name, dag=True, type="xgmPalette")):
            error_msg = (
                "Validation failed because there are no meshes in the scene "
                "to export xgen collection for. You can uncheck this plugin or create "
                "xgen collection."
            )
            self.logger.error(error_msg)
            raise Exception(error_msg)

        # get the configured work file template
        work_template = item.parent.properties.get("work_template")
        publish_template = item.properties.get("publish_template")
        self.logger.debug("work_template:---%s"%work_template)

        work_fields = work_template.get_fields(path)
        object_display = re.sub(r'[\W_]+', '', collection_name)
        work_fields["name"] = object_display
        work_fields["xgcollection"] = collection_name

        # set the display name as the name to use in SG to represent the publish
        item.properties["publish_name"] = object_display

        # ensure the fields work for the publish template
        missing_keys = publish_template.missing_keys(work_fields)
        if missing_keys:
            error_msg = "Work file '%s' missing keys required for the " \
                        "publish template: %s" % (path, missing_keys)
            self.logger.error(error_msg)
            raise Exception(error_msg)

        # create the publish path by applying the fields. store it in the item's
        # properties. Also set the publish_path to be explicit.
        self.logger.debug("work_fields:--%s"%work_fields)
        item.properties["path"] = publish_template.apply_fields(work_fields)
        # item.properties["publish_path"] = item.properties["path"]

        # use the work file's version number when publishing
        if "version" in work_fields:
            item.properties["publish_version"] = work_fields["version"]

        # run the base class validation
        return super(MayaXGenShaderPublishPlugin, self).validate(
            settings, item)

    def publish(self, settings, item):

        publisher = self.parent
        # self.logger.debug("ppcontext:----%s----" % item.context)
        # self.logger.debug("pptask:----%s----" % item.context.task)

        # get the path to create and publish
        publish_path = item.properties["path"]

        # ensure the publish folder exists:
        publish_folder = os.path.dirname(publish_path)
        publisher.ensure_folder_exists(publish_folder)
        collection = item.properties["collection"]
        # now just export shaders for this item to the publish path. there's
        # probably a better way to do this.
        try:
            import xgenm as xg
        except Exception, e:
            self.logger.debug(e)
            return
        descriptions = xg.descriptions(collection)

        # now just export shaders for this item to the publish path. there's
        # probably a better way to do this.
        shading_groups = set()
        shad_group_to_obj = {}
        for des in descriptions:
            des_shape = cmds.listRelatives(des, shapes=True)
            shading = cmds.listConnections(des_shape[0], type="shadingEngine")
            for shading_group in shading:
                shading_groups.add(shading_group)
                element = cmds.listAttr("%s.dagSetMembers" % (shading_group),
                                        m=True)  # dagSetMembers[0],dagSetMembers[1]
                for ele in element:
                    connection_obj = cmds.listConnections("%s.%s" % (shading_group, ele))
                    if not connection_obj:
                        continue
                    for obj in connection_obj:
                        long_name = cmds.ls(obj, l=True)[0]
                        shad_group_to_obj.setdefault(shading_group, set()).add(long_name)
        # print "group:",shad_group_to_obj
        shaders = set()
        script_nodes = []
        for shading_group in list(shading_groups):
            connections = cmds.listConnections(
                shading_group,
                source=True,
                destination=False
            )
            for shader in cmds.ls(connections, materials=True):
                # print "shader:", shader
                shaders.add(shader)
                objects = list(shad_group_to_obj[shading_group])
                for obj in objects:

                    # get rid of namespacing
                    if obj.startswith("|"):
                        obj = obj[1:]

                    # get real name
                    name = []
                    sp_name_space = obj.split("|")
                    for ns in sp_name_space:
                        name.append(ns.split(":")[-1])
                    obj_parts = '|'.join(name)
                    script_node_name = "XGSHADER_HOOKUP_" + obj_parts#[-1]
                    script_node = cmds.scriptNode(
                        name=script_node_name,
                        scriptType=0,  # execute on demand.
                        beforeScript=shader,
                    )
                    # print "script_node:",script_node
                    script_nodes.append(script_node)

        if not shaders:
            self.logger.debug("No shader network found to export and publish.")
            return

        select_nodes = list(shaders)
        select_nodes.extend(script_nodes)

        cmds.select(select_nodes, replace=True)
        self.logger.debug("shader_node:%s"%select_nodes)
        # write .ma file to the publish path with the shader network definitions
        cmds.file(
            publish_path,
            type='mayaAscii',
            exportSelected=True,
            options="v=0",
            prompt=False,
            force=True
        )

        # clean up shader hookup nodes. they should exist in publish file only
        _clean_shader_hookup_script_nodes()

        # set the publish type in the item's properties. the base plugin will
        # use this when registering the file with Shotgun
        item.properties["publish_type"] = "MAYA XGShader"

        # Now that the path has been generated, hand it off to the base publish
        # plugin to do all the work to register the file with SG
        super(MayaXGenShaderPublishPlugin, self).publish(settings, item)

def _session_path():
    """
    Return the path to the current session
    :return:
    """
    path = cmds.file(query=True, sn=True)

    if isinstance(path, unicode):
        path = path.encode("utf-8")

    return path


def _get_save_as_action():
    """
    Simple helper for returning a log action dict for saving the session
    """

    engine = sgtk.platform.current_engine()

    # default save callback
    callback = cmds.SaveScene

    # if workfiles2 is configured, use that for file save
    if "tk-multi-workfiles2" in engine.apps:
        app = engine.apps["tk-multi-workfiles2"]
        if hasattr(app, "show_file_save_dlg"):
            callback = app.show_file_save_dlg

    return {
        "action_button": {
            "label": "Save As...",
            "tooltip": "Save the current session",
            "callback": callback
        }
    }


def _clean_shader_hookup_script_nodes():

    # clean up any existing shader hookup nodes
    hookup_prefix = "XGSHADER_HOOKUP_"
    for node in cmds.ls(type="script"):
        if node.startswith(hookup_prefix):
            cmds.delete(node)

