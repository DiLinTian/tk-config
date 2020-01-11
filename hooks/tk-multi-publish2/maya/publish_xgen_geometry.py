#!/usr/bin/env python
# -*- coding:utf-8 -*-
'''
@ author：huangsheng
@ date: 2020/1/3 13:37
@ description:
    

'''

import os
import re
import maya.cmds as cmds
import maya.mel as mel
import sgtk


# this method returns the evaluated hook base class. This could be the Hook
# class defined in Toolkit core or it could be the publisher app's base publish
# plugin class as defined in the configuration.
HookBaseClass = sgtk.get_hook_baseclass()


class MayaXGenGeometryPublishPlugin(HookBaseClass):
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
        This plugin handles exporting and publishing Maya XGen Geomery.
        Collected xgen shaders are exported to disk as .ma files that can
        be loaded by artists downstream. This is a simple, example
        implementation and not meant to be a robust, battle-tested solution for
        shader or texture management on production.
        </p>
        """

    @property
    def settings(self):

        plugin_settings = super(MayaXGenGeometryPublishPlugin, self).settings or {}

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

        return ["maya.session.xggeometry"]

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

        if not path:
            # the session still requires saving. provide a save button.
            # validation fails.
            error_msg = "The Maya session has not been saved."
            self.logger.error(
                error_msg,
                extra=_get_save_as_action()
            )
            raise Exception(error_msg)

        path = sgtk.util.ShotgunPath.normalize(path)

        xg_geometry = item.properties["geometry"]
        self.logger.debug("publish_geometry:%s"%xg_geometry)
        # check that there is still geometry in the scene:
        if (not cmds.ls(xg_geometry, dag=True, type="mesh")):
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
        # get the current scene path and extract fields from it using the work
        # template:
        work_fields = work_template.get_fields(path)
        object_display = re.sub(r'[\W_]+', '', xg_geometry)
        work_fields["name"] = object_display
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
        return super(MayaXGenGeometryPublishPlugin, self).validate(
            settings, item)

    def publish(self, settings, item):
        publisher = self.parent
        # get the path to create and publish
        publish_path = item.properties["path"]
        publish_path = replaceSpecialCharacter(publish_path)

        geo = item.properties['geometry']
        fullname = cmds.ls(geo,l = True)
        if len(fullname)>1:
            raise Exception("More than one '%s' exists!"%geo)
        parent = fullname[0].split("|")[1]
        publisher.ensure_folder_exists(os.path.split(publish_path)[0])
        cmds.select(parent,r = True)
        cmds.file(
            publish_path,
            type='mayaAscii',
            exportSelected=True,
            options="v=0",
            prompt=False,
            force=True
        )
        self.logger.info("A Publish will be created in Shotgun and linked to:")
        self.logger.info("  %s" % (publish_path))

        item.properties["publish_type"] = "MAYA XGGeometry"
        super(MayaXGenGeometryPublishPlugin, self).publish(settings, item)
def replaceSpecialCharacter(strings):
    if "\a" in strings:
        strings = strings.replace("\a", "/a")
    if "\b" in strings:
        strings = strings.replace("\b", "/b")
    if "\e" in strings:
        strings = strings.replace("\e", "/e")
    if "\n" in strings:
        strings = strings.replace("\n", "/n")
    if "\v" in strings:
        strings = strings.replace("\v", "/v")
    if "\r" in strings:
        strings = strings.replace("\r", "/r")
    if "\t" in strings:
        strings = strings.replace("\t", "/t")
    if "\f" in strings:
        strings = strings.replace("\f", "/f")
    return strings.replace("\\","/")
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
