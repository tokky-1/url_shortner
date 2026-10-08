from sqlalchemy import Column,String,BigInteger,Integer,DateTime,func
from sqlalchemy.orm import relationship
from db.connect import Base

class URL(Base):
    __tablename__ = "Urls"
    id = Column(BigInteger,autoincrement=True,primary_key=True,nullable=False)
    original_url = Column(String,nullable=False)
    clicks = Column(Integer,unique=True,nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(),nullable=False)
