"""ของปลอมใช้ร่วมกันในเทสต์เกม (ไม่ต้องต่อ Discord)"""


class U:
    def __init__(self, uid, name, manage=False):
        self.id, self.display_name, self.bot = uid, name, False
        self.guild_permissions = type("P", (), {"manage_messages": manage})()


class Resp:
    def __init__(self):
        self.sent, self.edited, self.modals = [], [], []

    async def send_message(self, c=None, **kw):
        self.sent.append(c)

    async def edit_message(self, **kw):
        self.edited.append(kw)

    async def send_modal(self, m):
        self.modals.append(m)


class I:
    def __init__(self, u):
        self.user, self.response = u, Resp()


class Msg:
    def __init__(self):
        self.kw = {}

    async def edit(self, **kw):
        self.kw = kw
