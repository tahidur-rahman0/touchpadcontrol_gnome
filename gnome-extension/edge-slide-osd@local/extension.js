import Gio from 'gi://Gio';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const IFACE = `
<node>
  <interface name="org.gnome.Shell.Extensions.EdgeSlide">
    <method name="ShowOSD">
      <arg type="s" direction="in" name="icon"/>
      <arg type="d" direction="in" name="level"/>
    </method>
  </interface>
</node>`;

export default class EdgeSlideOsd extends Extension {
    enable() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, '/org/gnome/Shell/Extensions/EdgeSlide');
    }

    disable() {
        this._dbus?.unexport();
        this._dbus = null;
    }

    ShowOSD(icon, level) {
        const gicon = Gio.Icon.new_for_string(icon);
        Main.osdWindowManager.showAll(gicon, null, Math.max(0, Math.min(1, level)), 1);
    }
}
