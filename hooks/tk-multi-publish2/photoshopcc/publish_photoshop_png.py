import os
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()

# custom publish png for photoshop
class PhotoshopCCPNGPublishPlugin(HookBaseClass):
    """
    Plugin for publishing an open nuke studio project.

    This hook relies on functionality found in the base file publisher hook in
    the publish2 app and should inherit from it in the configuration. The hook
    setting for this plugin should look something like this::

        hook: "{self}/publish_file.py:{engine}/tk-multi-publish2/basic/publish_document.py"

    """

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does. This can
        contain simple html for formatting.
        """


        return """
        <p>
        This plugin handles publishing a png  by photoshop.
        </p>
        """ 
        # TODO: add link to workflow docs

    @property
    def settings(self):
        """
        Dictionary defining the settings that this plugin expects to receive
        through the settings parameter in the accept, validate, publish and
        finalize methods.

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

        # inherit the settings from the base publish plugin
        plugin_settings = \
            super(PhotoshopCCPNGPublishPlugin, self).settings or {}

        # settings specific to this class
        photoshop_png_settings = {
            "Publish Template": {
                "type": "template",
                "default": None,
                "description": "Template path for published work files. Should"
                               "correspond to a template defined in "
                               "templates.yml.",
            },

        }

        # update the base settings
        plugin_settings.update(photoshop_png_settings)

        return plugin_settings

    @property
    def item_filters(self):
        """
        List of item types that this plugin is interested in.

        Only items matching entries in this list will be presented to the
        accept() method. Strings can contain glob patters such as *, for example
        ["maya.*", "file.maya"]
        """
        return ["photoshop.document.png"]

    def accept(self, settings, item):
        """
        Method called by the publisher to determine if an item is of any
        interest to this plugin. Only items matching the filters defined via the
        item_filters property will be presented to this method.

        A publish task will be generated for each item accepted here. Returns a
        dictionary with the following booleans:

            - accepted: Indicates if the plugin is interested in this value at
               all. Required.
            - enabled: If True, the plugin will be enabled in the UI, otherwise
                it will be disabled. Optional, True by default.
            - visible: If True, the plugin will be visible in the UI, otherwise
                it will be hidden. Optional, True by default.
            - checked: If True, the plugin will be checked in the UI, otherwise
                it will be unchecked. Optional, True by default.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process

        :returns: dictionary with boolean keys accepted, required and enabled
        """
        accepted = True
        publisher = self.parent

        template_name = settings["Publish Template"].value
        self.logger.debug("template_name: ---%s----" % template_name)

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
            "accepted": True,
            "checked": True
        }

    def validate(self, settings, item):
        """
        Validates the given item to check that it is ok to publish.

        Returns a boolean to indicate validity.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process

        :returns: True if item is valid, False otherwise.
        """

        publisher = self.parent
        engine = publisher.engine
        png_name = item.properties["png_name"]
        document = item.parent.properties['document']
        path = _document_path(document)
        # ---- ensure the document has been saved

        if not path:
            # the document still requires saving. provide a save button.
            # validation fails.
            error_msg = "The Photoshop document '%s' has not been saved." % \
                        (document.name,)
            self.logger.error(
                error_msg,
                extra=_get_save_as_action(document)
            )
            raise Exception(error_msg)

        # ---- check the document against any attached work template

        # get the path in a normalized state. no trailing separator,
        # separators are appropriate for current os, no double separators,
        # etc.
        path = sgtk.util.ShotgunPath.normalize(path)

        # if the document item has a known work template, see if the path
        # matches. if not, warn the user and provide a way to save the file to
        # a different path
        work_template = item.parent.properties.get("work_template")
        publish_template = item.properties.get("publish_template")

        self.logger.debug("publish_template:----%s----" % publish_template)

        work_fields = work_template.get_fields(path)

        # include the camera name in the fields
        work_fields["name"] = png_name

        # ensure the fields work for the publish template
        missing_keys = publish_template.missing_keys(work_fields)
        if missing_keys:
            error_msg = "Work file '%s' missing keys required for the " \
                        "publish template: %s" % (path, missing_keys)
            self.logger.error(error_msg)
            raise Exception(error_msg)

        # create the publish path by applying the fields. store it in the item's
        # properties. This is the path we'll create and then publish in the base
        # publish plugin. Also set the publish_png_path to be explicit.
        publish_png_path = publish_template.apply_fields(work_fields)
        self.logger.debug("publish_path:------%s------"%publish_png_path)
        item.properties["path"] = publish_png_path
        item.properties["publish_png_path"] = publish_png_path
        # use the work file's version number when publishing
        if "version" in work_fields:
            item.properties["publish_version"] = work_fields["version"]

        return super(PhotoshopCCPNGPublishPlugin, self).validate(
            settings, item)

    def publish(self, settings, item):
        """
        Executes the publish logic for the given item and settings.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """
        publisher = self.parent
        engine = publisher.engine
        document = item.parent.properties["document"]
        adobe = engine.adobe

        publish_png_path = item.properties["publish_png_path"]
        publish_folder = os.path.dirname(publish_png_path)
        self.parent.ensure_folder_exists(publish_folder)

        png_name = item.properties['png_name']
        png_opt = adobe.PNGSaveOptions()
        document.saveAs(adobe.File(publish_png_path),png_opt,True)
        # let the base class register the publish
        super(PhotoshopCCPNGPublishPlugin, self).publish(settings, item)
        

    # def finalize(self, settings, item):
    #     """
    #     Execute the finalization pass. This pass executes once all the publish
    #     tasks have completed, and can for example be used to version up files.

    #     :param settings: Dictionary of Settings. The keys are strings, matching
    #         the keys returned in the settings property. The values are `Setting`
    #         instances.
    #     :param item: Item to process
    #     """

    #     publisher = self.parent
    #     engine = publisher.engine

    #     # do the base class finalization
    #     super(PhotoshopCCPNGPublishPlugin, self).finalize(settings, item)

    #     document = item.properties.get("document")
    #     path = item.properties["path"]

    #     # we need the path to be saved for this document. ensure the document
    #     # is provided and allow the base method to supply the new path
    #     save_callback = lambda path, d=document: engine.save_to_path(d, path)

    #     # bump the document path to the next version
    #     self._save_to_next_version(path, item, save_callback)


def _get_save_as_action(document):
    """
    Simple helper for returning a log action dict for saving the document
    """

    engine = sgtk.platform.current_engine()

    # default save callback
    callback = lambda: engine.save_as(document)

    # if workfiles2 is configured, use that for file save
    if "tk-multi-workfiles2" in engine.apps:
        app = engine.apps["tk-multi-workfiles2"]
        if hasattr(app, "show_file_save_dlg"):
            callback = app.show_file_save_dlg

    return {
        "action_button": {
            "label": "Save As...",
            "tooltip": "Save the current document",
            "callback": callback
        }
    }


def _document_path(document):
    """
    Returns the path on disk to the supplied document. May be ``None`` if the
    document has not been saved.
    """

    try:
        path = document.fullName.fsName
    except Exception:
        path = None

    return path
