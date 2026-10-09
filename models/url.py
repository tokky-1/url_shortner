from sqlalchemy import Column,Text,BigInteger,Integer,DateTime,func
from db.connect import Base

class URL(Base):
    __tablename__ = "urls"
    id = Column(BigInteger,autoincrement=True,primary_key=True,nullable=False)
    original_url = Column(Text,nullable=False)
    clicks = Column(Integer,nullable=False,default=0,server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now(),nullable=False)
