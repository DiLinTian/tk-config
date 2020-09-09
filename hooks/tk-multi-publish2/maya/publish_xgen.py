#!/usr/bin/env python
# -*- coding:utf-8 -*-
'''
@ author：huangsheng
@ date: 2019/12/30 13:48
@ description:
    

'''


import os
import re
import sys
import maya.cmds as cmds
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()


class MayaXGenPublishPlugin(HookBaseClass):

    @property
    def description(self):

        return """
        <p>
        This plugin handles exporting and publishing Maya XGen.
        Collected mesh shaders are exported to disk as .ma files that can
        be loaded by artists downstream. This is a simple, example
        implementation and not meant to be a robust, battle-tested solution for
        shader or texture management on production.
        </p>
        """

    @property
    def settings(self):

        plugin_settings = super(MayaXGenPublishPlugin, self).settings or {}

        # settings specific to this class
        xgen_publish__settings = {
            "Publish Template": {
                "type": "template",
                "default": None,
                "description": "Template path for published shader networks. "
                               "Should correspond to a template defined in "
                               "templates.yml.",
            }
        }

        # update the base settings
        plugin_settings.update(xgen_publish__settings)

        return plugin_settings

    @property
    def item_filters(self):
        return ["maya.session.xgen"]

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
        _ext = os.path.splitext(path)[-1]
        project_root, basename = os.path.split(path)
        basename = basename.split(_ext)[0]
        collection = item.properties['collection']

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

        object_name = item.properties["collection"]
        self.logger.debug("object_name:%s" % object_name)
        # check that there is still geometry in the scene:
        if (not cmds.ls(object_name, dag=True, type="xgmPalette")):
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
        self.logger.debug("work_template:---%s" % work_template)
        # get the current scene path and extract fields from it using the work
        # template:
        work_fields = work_template.get_fields(path)
        work_fields["xgfilename"] = basename + "__" + collection

        # we want to override the {name} token of the publish path with the
        # name of the object being exported. get the name stored by the
        # collector and remove any non-alphanumeric characters
        object_display = re.sub(r'[\W_]+', '', object_name)
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

        item.properties["path"] = publish_template.apply_fields(work_fields)
        # use the work file's version number when publishing
        if "version" in work_fields:
            item.properties["publish_version"] = work_fields["version"]
        self.logger.debug("version:%s"%item.properties["publish_version"])

        # run the base class validation



        return super(MayaXGenPublishPlugin, self).validate(
            settings, item)

    def publish(self, settings, item):

        # save the file
        cmds.file(save = True)

        publisher = self.parent
        path = _session_path()
        _ext = os.path.splitext(path)[-1]
        project_root,basename = os.path.split(path)
        # basename = basename.split(_ext)[0]

        # get the path to create and publish
        publish_path = item.properties["path"]
        publish_dir = os.path.dirname(publish_path)
        collection_path = item.properties['collection_path']
        collection = item.properties['collection']
        # ensure the publish folder exists:
        publisher.ensure_folder_exists(publish_dir)
        # copy work's collection to publish path
        _, folder = os.path.split(collection_path)
        dst = os.path.join(publish_dir, folder)
        sgtk.util.filesystem.copy_folder(collection_path, dst)

        # export .xgen
        try:
            import xgenm as xg
        except Exception,e:
            self.logger.debug(e)
            return
        xg.exportPalette(collection,publish_path)
        # change xgProjectPath
        publish_path_root = project_root.replace("/work/","/publish/") + "/"
        changeXGenProjectPath(publish_path,
                              publish_path_root,
                              item.properties["publish_version"],
                              collection,
                              self.logger)

        self.logger.info("A Publish will be created in Shotgun and linked to:")
        self.logger.info("  %s" % (publish_path))
        # publish the path to shotgun

        item.properties["publish_type"] = "Maya XGen"

        # plugin to do all the work to register the file with SG
        super(MayaXGenPublishPlugin, self).publish(settings, item)
def changeXGenProjectPath(xgen,project_path,version,collection,logger):
    xgProjectPath = "xgProjectPath"
    xgDataPath = "xgDataPath"
    from func import replace_special_character as rsc
    rep_path = rsc.replaceSpecialCharacter(project_path)
    # rep_path = rep_path.replace("\\","/")
    logger.debug("replace_path:%s" % rep_path)

    new_data_path = ""
    with open(xgen,"r") as f:
        lines = f.readlines()
        for i in xrange(len(lines)):
            if re.search(xgProjectPath,lines[i]):
                lines[i] = re.sub("/work/","/publish/",lines[i])
            if re.search(xgDataPath, lines[i]):
                if not new_data_path:
                    sp = lines[i].split('/collections/')
                    new_data_path = '{dir}/collections/{version}/{col_name}\n'.format(
                        dir = sp[0],
                        version = 'v%03d'%int(version),
                        col_name = collection
                    )
                    new_data_path = re.sub("/work/","/publish/",new_data_path)
                lines[i] = new_data_path
    with open(xgen,"w") as f:
        f.writelines(lines)
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


