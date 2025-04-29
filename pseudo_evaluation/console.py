class node:
    def __init__(self,data):
        self.data=data
        self.next=None
class list:
    def __init__(self):
        self.head=None
        
    def insertatbegg(self,val):
        if self.head is None:
            self.head=node(val)
        else:
            new_node = node(val)
            new_node.next=self.head
            self.head=new_node
    def insertatmid(self,val,index):
        current=self.head
        counter=0
        while current and counter<index:
            current=current.next
            counter+=1
        new_node=node(val)
        new_node.next=current.next
        current.next=new_node
    
        