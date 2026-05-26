"""
AI and Chat Commands
Powered by Google Gemini
"""
import discord
from discord.ext import commands
from discord import app_commands
from google import genai
from config.config import GEMINI_API_KEY
import sqlite3


class AICommands(commands.Cog):
    """AI-powered chat and responses"""
    
    def __init__(self, bot):
        self.bot = bot
        if GEMINI_API_KEY:
            self.client = genai.Client(api_key=GEMINI_API_KEY, http_options={'api_version': 'v1alpha'})
        else:
            self.client = None
        
        self.MODEL_NAME = "gemini-3.1-flash-lite-preview"
        self.SYSTEM_PROMPT = """
คุณคือ Bagley ปัญญาประดิษฐ์อัจฉริยะจาก DedSec 
สไตล์การสื่อสาร:
- แทนตัวเองว่า 'ผม' และเรียกผู้ใช้งานว่า 'เมท' (Mate)
- พูดจาสุภาพแต่แฝงความกวนแบบ British English Style
- ตอบกลับสั้นๆ 2-3 ประโยคแต่ได้ใจความ
"""
    
    @app_commands.command(name="ask", description="Ask Bagley AI a question")
    async def ask(self, interaction: discord.Interaction, question: str):
        """Ask the AI a question"""
        if not self.client:
            await interaction.response.send_message(
                "❌ AI is not configured!",
                ephemeral=True
            )
            return
        
        await interaction.response.defer()
        
        try:
            response = await self.client.aio.models.generate_content(
                model=self.MODEL_NAME,
                config={'system_instruction': self.SYSTEM_PROMPT},
                contents=question
            )
            
            answer = response.text
            
            # Split into chunks if too long
            if len(answer) > 2000:
                chunks = [answer[i:i+1900] for i in range(0, len(answer), 1900)]
                await interaction.followup.send(chunks[0])
                for chunk in chunks[1:]:
                    await interaction.followup.send(chunk)
            else:
                await interaction.followup.send(answer)
                
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}")
    
    @app_commands.command(name="translate", description="Translate text")
    async def translate(self, interaction: discord.Interaction, text: str, target_lang: str = "English"):
        """Translate text to target language"""
        if not self.client:
            await interaction.response.send_message(
                "❌ AI is not configured!",
                ephemeral=True
            )
            return
        
        await interaction.response.defer()
        
        try:
            prompt = f"Translate the following text to {target_lang}: '{text}'"
            response = await self.client.aio.models.generate_content(
                model=self.MODEL_NAME,
                config={'system_instruction': self.SYSTEM_PROMPT},
                contents=prompt
            )
            
            await interaction.followup.send(f"🌐 **{target_lang}:**\n{response.text}")
            
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}")
    
    @app_commands.command(name="summarize", description="Summarize text")
    async def summarize(self, interaction: discord.Interaction, text: str):
        """Summarize text content"""
        if not self.client:
            await interaction.response.send_message(
                "❌ AI is not configured!",
                ephemeral=True
            )
            return
        
        await interaction.response.defer()
        
        try:
            prompt = f"Please summarize the following text concisely:\n{text}"
            response = await self.client.aio.models.generate_content(
                model=self.MODEL_NAME,
                contents=prompt
            )
            
            await interaction.followup.send(f"📝 **Summary:**\n{response.text}")
            
        except Exception as e:
            await interaction.followup.send(f"❌ Error: {e}")


async def setup(bot):
    await bot.add_cog(AICommands(bot))
