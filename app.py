from flask import Flask, request, abort

from linebot import (
    LineBotApi, WebhookHandler
)
from linebot.exceptions import (
    InvalidSignatureError
)
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,ImageSendMessage,StickerSendMessage,FollowEvent,UnfollowEvent,
)
from linebot.models import *
from database import db_session, init_db
from models.user import Users
from models.product import Products
from models.cart import Cart
from models.order import Orders
from models.item import Items
from config import Config
from models.linepay import LinePay
from urllib.parse import parse_qsl
import uuid


app = Flask(__name__)

line_bot_api = LineBotApi(Config.CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(Config.CHANNEL_SECRET)

app = Flask(__name__)


#建立或取得user
def get_or_create_user(user_id):
    #從id=user_id先搜尋有沒有這個user，如果有的話就會直接跳到return
    user = db_session.query(Users).filter_by(id=user_id).first()
    #沒有的話就會透過line_bot_api來取得用戶資訊
    if not user:
        profile = line_bot_api.get_profile(user_id)
        #然後再建立user並且存入到資料庫當中
        user = Users(id=user_id, nick_name=profile.display_name, image_url=profile.picture_url)
        db_session.add(user)
        db_session.commit()

    return user


def about_us_event(event):
    emoji = [
            {
                "index": 0,
                "productId": "5ac21184040ab15980c9b43a",
                "emojiId": "225"
            },
            {
                "index": 23,
                "productId": "5ac21184040ab15980c9b43a",
                "emojiId": "225"
            }
        ]

    text_message = TextSendMessage(text='''$ Super Easy Assistant $
Hello! 您好，歡迎您成為 Super Easy Assistant 的好友！

我是 Your Dear 支付小幫手 

-這裡有超級商場，還可以選購商品喔~
                                   
-直接點選下方各項選單功能

-期待您的光臨！''', emojis=emoji)

    sticker_message = StickerSendMessage(
        package_id='8522',
        sticker_id='16581271'
    )
    line_bot_api.reply_message(
        event.reply_token,
        [text_message, sticker_message])
    
# 監聽所有來自 /callback 的 Post Request
@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'
	
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    
    get_or_create_user(event.source.user_id)
    #profile = line_bot_api.get_profile(event.source.user_id)
    cart = Cart(user_id = event.source.user_id)
    #uid = profile.user_id
    message_text = str(event.message.text).lower()

##################################使用說明 選單###############################################
    if message_text == '@使用說明':
        about_us_event(event)
    elif message_text in ['我想訂購商品', 'add']:
        message = Products.list_all()
    elif "i'd like to have" in message_text:
        product_name = message_text.split(',')[0]
        num_item = message_text.rsplit(':')[1]
        product = db_session.query(Products).filter(Products.name.ilike(product_name)).first()

        if product:

            cart.add(product=product_name, num=num_item)
            #然後利用confirm_template的格式詢問用戶是否還要加入？
            confirm_template = ConfirmTemplate(
                text='Sure, {} {}, anything else?'.format(num_item, product_name),
                actions=[
                    MessageAction(label='Add', text='add'),
                    MessageAction(label="That's it", text="That's it")
                ])

            message = TemplateSendMessage(alt_text='anything else?', template=confirm_template)

        else:
            message = TextSendMessage(text="Sorry, we don't have {}".format(product_name))

        print(cart.bucket())

    elif message_text in ['my cart', 'cart', "that's it"]:
        
        if cart.bucket():
            message = cart.display()
        else:
            message = TextSendMessage(text='Your cart is empty now.')

    elif message_text == 'empty cart':

        cart.reset()
        message = TextSendMessage(text='Your cart is empty now.')
    
    if message:
        line_bot_api.reply_message(
            event.reply_token,message)


#@handler.add(FollowEvent)
#def handle_follow(event):
#    welcome_msg = """  """

@handler.add(PostbackEvent)
def handle_postback(event):
    data = dict(parse_qsl(event.postback.data))#先將postback中的資料轉成字典

    action = data.get('action')#再get action裡面的值

    if action == 'checkout':#如果action裡面的值是checkout的話才會執行結帳的動作

        user_id = event.source.user_id#取得user_id

        cart = Cart(user_id=user_id)#透過user_id取得購物車

        if not cart.bucket():#判斷購物車裡面有沒有資料，沒有就回傳購物車是空的
            message = TextSendMessage(text='Your cart is empty now.')

            line_bot_api.reply_message(event.reply_token, [message])

            return 'OK'

        order_id = uuid.uuid4().hex#如果有訂單的話就會使用uuid的套件來建立，因為它可以建立獨一無二的值

        total = 0 #總金額
        items = [] #暫存訂單項目

        for product_name, num in cart.bucket().items():#透過迴圈把項目轉成訂單項目物件
            #透過產品名稱搜尋產品是不是存在
            product = db_session.query(Products).filter(Products.name.ilike(product_name)).first()
            #接著產生訂單項目的物件
            item = Items(product_id=product.id,
                         product_name=product.name,
                         product_price=product.price,
                         order_id=order_id,
                         quantity=num)

            items.append(item)

            total += product.price * int(num)#訂單價格 * 訂購數量
        #訂單項目物件都建立後就會清空購物車
        cart.reset()
        #建立LinePay的物件
        line_pay = LinePay()
        #再使用line_pay.pay的方法，最後就會回覆像postman的格式
        info = line_pay.pay(product_name='LSTORE',
                            amount=total,
                            order_id=order_id,
                            product_image_url=Config.STORE_IMAGE_URL)
        #取得付款連結和transactionId後
        pay_web_url = info['paymentUrl']['web']
        transaction_id = info['transactionId']
        #接著就會產生訂單
        order = Orders(id=order_id,
                       transaction_id=transaction_id,
                       is_pay=False,
                       amount=total,
                       user_id=user_id)
        #接著把訂單和訂單項目加入資料庫中
        db_session.add(order)

        for item in items:
            db_session.add(item)

        db_session.commit()
        #最後告知用戶並提醒付款
        message = TemplateSendMessage(
            alt_text='Thank you, please go ahead to the payment.',
            template=ButtonsTemplate(
                text='Thank you, please go ahead to the payment.',
                actions=[
                    URIAction(label='Pay NT${}'.format(order.amount),
                              uri=pay_web_url)
                ]))

        line_bot_api.reply_message(event.reply_token, [message])

    return 'OK'

@app.route("/confirm")
def confirm():
    transaction_id = request.args.get('transactionId')
    order = db_session.query(Orders).filter(Orders.transaction_id == transaction_id).first()

    if order:
        line_pay = LinePay()
        line_pay.confirm(transaction_id=transaction_id, amount=order.amount)

        order.is_pay = True#確認收款無誤時就會改成已付款
        db_session.commit()
        
        #傳收據給用戶
        message = order.display_receipt()
        line_bot_api.push_message(to=order.user_id, messages=message)

        return '<h1>Your payment is successful. thanks for your purchase.</h1>'
    
#初始化產品資訊
@app.before_first_request
def init_products():
    # init db
    result = init_db()#先判斷資料庫有沒有建立，如果還沒建立就會進行下面的動作初始化產品
    if result:
        init_data = [Products(name='絨毛玩偶',
                              product_image_url='https://imgur.com/bJjKXes.jpg',
                              price=1000,
                              description='15cm 大小的填充玩偶，可在手上把玩的噴火龍'),
                     Products(name='造型布偶',
                              product_image_url='https://imgur.com/58DTtMq.jpg',
                              price=500,
                              description='可愛又迷人的四四方方玩偶，有各種不同的大小'),
                     Products(name='和菓子',
                              price=50,
                              product_image_url='https://imgur.com/Fo8CHK0.jpg',
                              description='有著皮卡丘的外型，有著甜美口味的糖果')]
        db_session.bulk_save_objects(init_data)#透過這個方法一次儲存list中的產品
        db_session.commit()#最後commit()才會存進資料庫
        #記得要from models.product import Products在app.py
        
if __name__ == "__main__":
    init_products()
    app.run()
